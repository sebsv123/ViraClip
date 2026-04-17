-- Add advanced AI polish settings to tasks
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS auto_center_face BOOLEAN DEFAULT FALSE;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS eye_contact_correction BOOLEAN DEFAULT FALSE;
