"""
Fine-tuning script for Llama-3.1 using Unsloth.
Optimized for ViraClip virality detection.
"""

import os
import torch
from unsloth import FastLanguageModel
from datasets import load_dataset
from trl import SFTTrainer
from transformers import TrainingArguments
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_fine_tuning(
    dataset_path="viral_dataset.jsonl",
    model_name="unsloth/meta-llama-3.1-8b-bnb-4bit",
    output_dir="backend/models/virality_lora",
    max_seq_len=2048,
):
    # 1. Load Model and Tokenizer
    logger.info(f"Loading base model: {model_name}")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=model_name,
        max_seq_length=max_seq_len,
        load_in_4bit=True,
    )

    # 2. Add LoRA Adapters
    logger.info("Adding LoRA adapters...")
    model = FastLanguageModel.get_peft_model(
        model,
        r=16, # Rank
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj",],
        lora_alpha=16,
        lora_dropout=0,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=3407,
        use_rslora=False,
        loftq_config=None,
    )

    # 3. Load Dataset
    logger.info(f"Loading dataset from {dataset_path}")
    dataset = load_dataset("json", data_files=dataset_path, split="train")

    def formatting_prompts_func(examples):
        instructions = examples["instruction"]
        inputs       = examples["input"]
        outputs      = examples["output"]
        texts = []
        for instruction, input, output in zip(instructions, inputs, outputs):
            # Alpaca format style
            text = f"### Instruction:\n{instruction}\n\n### Input:\n{input}\n\n### Response:\n{output}" + tokenizer.eos_token
            texts.append(text)
        return { "text" : texts, }

    dataset = dataset.map(formatting_prompts_func, batched = True,)

    # 4. Trainer
    logger.info("Initializing trainer...")
    trainer = SFTTrainer(
        model = model,
        tokenizer = tokenizer,
        train_dataset = dataset,
        dataset_text_field = "text",
        max_seq_length = max_seq_len,
        dataset_num_proc = 2,
        packing = False, 
        args = TrainingArguments(
            per_device_train_batch_size = 2,
            gradient_accumulation_steps = 4,
            warmup_steps = 5,
            max_steps = 60, # Small example for demo, increase for production
            learning_rate = 2e-4,
            fp16 = not torch.cuda.is_bf16_supported(),
            bf16 = torch.cuda.is_bf16_supported(),
            logging_steps = 1,
            optim = "adamw_8bit",
            weight_decay = 0.01,
            lr_scheduler_type = "linear",
            seed = 3407,
            output_dir = "outputs",
        ),
    )

    # 5. Train
    logger.info("Starting training loop...")
    trainer.train()

    # 6. Save LoRA Adapters
    logger.info(f"Saving fine-tuned adapters to {output_dir}")
    model.save_pretrained_lora(output_dir)
    tokenizer.save_pretrained(output_dir)
    logger.info("Fine-tuning complete!")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="viral_dataset.jsonl")
    args = parser.parse_args()
    
    if os.path.exists(args.dataset):
        run_fine_tuning(dataset_path=args.dataset)
    else:
        logger.error(f"Dataset file {args.dataset} not found. Run collect_dataset.py first.")
