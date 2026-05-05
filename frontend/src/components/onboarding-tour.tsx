"use client";

import { useState, useEffect } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Sparkles, TrendingUp, Zap, Download, ArrowRight, Check } from "lucide-react";
import { Progress } from "@/components/ui/progress";

interface OnboardingTourProps {
  onComplete: () => void;
}

const ONBOARDING_KEY = "viraclip_onboarding_completed";

export function OnboardingTour({ onComplete }: OnboardingTourProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [currentStep, setCurrentStep] = useState(0);

  useEffect(() => {
    // Check if user has completed onboarding
    const completed = localStorage.getItem(ONBOARDING_KEY);
    if (!completed) {
      // Delay showing modal slightly for better UX
      const timer = setTimeout(() => setIsOpen(true), 500);
      return () => clearTimeout(timer);
    }
  }, []);

  const steps = [
    {
      icon: Sparkles,
      title: "Welcome to ViraClip! ✨",
      description: "Transform long videos into viral-ready clips in minutes with AI-powered analysis.",
      details: [
        "Upload any video or paste a YouTube URL",
        "AI identifies the most engaging moments",
        "Get clips optimized for TikTok, Reels, and Shorts"
      ]
    },
    {
      icon: TrendingUp,
      title: "AI Virality Scoring 🎯",
      description: "Every clip gets a virality score (1-10) predicting its potential to go viral.",
      details: [
        "Score 8-10: High viral potential 🔥",
        "Score 6-7: Strong engagement potential ⚡",
        "Score 4-5: Good with optimization 📈",
        "Detailed metrics: Hook, Engagement, Value, Shareability"
      ]
    },
    {
      icon: Zap,
      title: "Smart Features ⚙️",
      description: "Professional tools to perfect your clips.",
      details: [
        "Auto-generated captions with multiple styles",
        "Face detection for optimal framing",
        "Hook type detection (question, statement, story...)",
        "Suggested social media copy and hashtags"
      ]
    },
    {
      icon: Download,
      title: "Export & Share 🚀",
      description: "Download clips optimized for your platform of choice.",
      details: [
        "One-click export for TikTok, Instagram, YouTube",
        "Preview before downloading",
        "Batch download multiple clips",
        "Ready-to-post with suggested copy"
      ]
    }
  ];

  const currentStepData = steps[currentStep];
  const Icon = currentStepData.icon;
  const progress = ((currentStep + 1) / steps.length) * 100;

  const handleNext = () => {
    if (currentStep < steps.length - 1) {
      setCurrentStep(currentStep + 1);
    } else {
      handleComplete();
    }
  };

  const handleSkip = () => {
    handleComplete();
  };

  const handleComplete = () => {
    localStorage.setItem(ONBOARDING_KEY, "true");
    setIsOpen(false);
    onComplete();
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => {
      if (!open) handleComplete();
    }}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <div className="flex items-center gap-2 mb-2">
            <div className="p-2 bg-purple-100 rounded-lg">
              <Icon className="w-6 h-6 text-purple-600" />
            </div>
            <div className="flex-1">
              <DialogTitle className="text-xl">{currentStepData.title}</DialogTitle>
              <p className="text-sm text-gray-500">
                Step {currentStep + 1} of {steps.length}
              </p>
            </div>
          </div>
          <Progress value={progress} className="h-1" />
        </DialogHeader>

        <div className="space-y-4 py-4">
          <DialogDescription className="text-base">
            {currentStepData.description}
          </DialogDescription>

          <div className="bg-gradient-to-br from-purple-50 to-blue-50 rounded-lg p-4 space-y-2">
            {currentStepData.details.map((detail, idx) => (
              <div key={idx} className="flex items-start gap-2">
                <Check className="w-4 h-4 text-green-600 mt-0.5 flex-shrink-0" />
                <p className="text-sm text-gray-700">{detail}</p>
              </div>
            ))}
          </div>

          {currentStep === steps.length - 1 && (
            <div className="bg-gradient-to-r from-purple-100 to-pink-100 border border-purple-200 rounded-lg p-4">
              <p className="text-sm text-purple-900 font-medium mb-2">
                🎉 You&apos;re all set! Ready to create viral content?
              </p>
              <p className="text-xs text-purple-700">
                Upload your first video to get started. Our AI will handle the rest!
              </p>
            </div>
          )}
        </div>

        <DialogFooter className="flex items-center justify-between">
          <Button 
            variant="ghost" 
            size="sm"
            onClick={handleSkip}
            className="text-gray-500"
          >
            Skip Tour
          </Button>

          <div className="flex items-center gap-2">
            {currentStep > 0 && (
              <Button 
                variant="outline" 
                size="sm"
                onClick={() => setCurrentStep(currentStep - 1)}
              >
                Back
              </Button>
            )}
            <Button 
              size="sm"
              onClick={handleNext}
              className="bg-purple-600 hover:bg-purple-700"
            >
              {currentStep < steps.length - 1 ? (
                <>
                  Next
                  <ArrowRight className="w-4 h-4 ml-1" />
                </>
              ) : (
                <>
                  Get Started
                  <Sparkles className="w-4 h-4 ml-1" />
                </>
              )}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// Hook to check if onboarding is needed
export function useOnboarding() {
  const [needsOnboarding, setNeedsOnboarding] = useState(false);

  useEffect(() => {
    const completed = localStorage.getItem(ONBOARDING_KEY);
    setNeedsOnboarding(!completed);
  }, []);

  const resetOnboarding = () => {
    localStorage.removeItem(ONBOARDING_KEY);
    setNeedsOnboarding(true);
  };

  return { needsOnboarding, resetOnboarding };
}
