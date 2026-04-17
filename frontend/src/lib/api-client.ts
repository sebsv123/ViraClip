/**
 * ViraClip API Client
 * Handles all communication with the Python FastAPI backend
 */

const API_BASE_URL = typeof window !== 'undefined' 
  ? window.location.origin.replace(':3000', ':8000')
  : 'http://localhost:8000';

export interface CreateTaskInput {
  source: string; // YouTube URL
  caption_template?: string;
  include_broll?: boolean;
  font_family?: string;
  font_size?: number;
  font_color?: string;
}

export interface Task {
  task_id: string;
  user_id: string;
  source_id?: string;
  status: string; // pending|processing|completed|failed
  created_at: string;
  updated_at: string;
}

export interface Clip {
  id: string;
  task_id: string;
  filename: string;
  duration: number;
  viral_score?: number;
  rating?: number;
  thumbs?: 'thumbs_up' | 'thumbs_down' | 'neutral';
  created_at: string;
}

export interface ProgressEvent {
  progress: number; // 0-100
  status: string;
  message?: string;
  clip_id?: string;
}

class ViraClipAPI {
  private baseUrl: string;

  constructor() {
    this.baseUrl = API_BASE_URL;
  }

  private async getHeaders(userId?: string): Promise<HeadersInit> {
    return {
      'Content-Type': 'application/json',
      ...(userId && { 'user_id': userId }),
    };
  }

  // ==================== TASKS ====================

  /**
   * Create a new video processing task
   */
  async createTask(data: CreateTaskInput, userId: string): Promise<{ task_id: string }> {
    const response = await fetch(`${this.baseUrl}/tasks`, {
      method: 'POST',
      headers: await this.getHeaders(userId),
      body: JSON.stringify(data),
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
      throw new Error(error.detail || `Failed to create task: ${response.statusText}`);
    }

    return response.json();
  }

  /**
   * Get task by ID
   */
  async getTask(taskId: string, userId: string): Promise<Task> {
    const response = await fetch(`${this.baseUrl}/tasks/${taskId}`, {
      headers: await this.getHeaders(userId),
    });

    if (!response.ok) {
      throw new Error(`Failed to fetch task: ${response.statusText}`);
    }

    return response.json();
  }

  /**
   * List all tasks for a user
   */
  async listTasks(userId: string, limit = 50): Promise<{ tasks: Task[]; total: number }> {
    const response = await fetch(`${this.baseUrl}/tasks?limit=${limit}`, {
      headers: await this.getHeaders(userId),
    });

    if (!response.ok) {
      throw new Error(`Failed to fetch tasks: ${response.statusText}`);
    }

    return response.json();
  }

  /**
   * Stream task progress via Server-Sent Events
   */
  streamTaskProgress(taskId: string, userId: string, onProgress: (event: ProgressEvent) => void): EventSource {
    const eventSource = new EventSource(
      `${this.baseUrl}/tasks/${taskId}/stream?user_id=${userId}`
    );

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as ProgressEvent;
        onProgress(data);

        // Auto-close on completion or failure
        if (data.status === 'completed' || data.status === 'failed') {
          eventSource.close();
        }
      } catch (error) {
        console.error('Failed to parse progress event:', error);
      }
    };

    eventSource.onerror = (error) => {
      console.error('SSE connection error:', error);
      eventSource.close();
    };

    return eventSource;
  }

  // ==================== CLIPS ====================

  /**
   * Get clip details by ID
   */
  async getClip(clipId: string, userId: string): Promise<Clip> {
    const response = await fetch(`${this.baseUrl}/clips/${clipId}`, {
      headers: await this.getHeaders(userId),
    });

    if (!response.ok) {
      throw new Error(`Failed to fetch clip: ${response.statusText}`);
    }

    return response.json();
  }

  /**
   * Rate a clip (1-5 stars)
   */
  async rateClip(clipId: string, rating: number, userId: string, taskId?: string): Promise<void> {
    const response = await fetch(`${this.baseUrl}/clips/${clipId}/rating`, {
      method: 'POST',
      headers: await this.getHeaders(userId),
      body: JSON.stringify({ rating, task_id: taskId }),
    });

    if (!response.ok) {
      throw new Error(`Failed to rate clip: ${response.statusText}`);
    }
  }

  /**
   * Give thumbs feedback on a clip
   */
  async thumbsClip(
    clipId: string,
    thumbs: 'thumbs_up' | 'thumbs_down' | 'neutral',
    userId: string,
    taskId?: string,
    feedbackText?: string
  ): Promise<void> {
    const response = await fetch(`${this.baseUrl}/clips/${clipId}/thumbs`, {
      method: 'POST',
      headers: await this.getHeaders(userId),
      body: JSON.stringify({ 
        rating: thumbs, 
        task_id: taskId,
        feedback_text: feedbackText 
      }),
    });

    if (!response.ok) {
      throw new Error(`Failed to submit feedback: ${response.statusText}`);
    }
  }

  /**
   * Download a clip
   */
  async downloadClip(clipId: string, userId: string, preset?: string): Promise<Blob> {
    const url = preset 
      ? `${this.baseUrl}/clips/${clipId}/export?preset=${preset}`
      : `${this.baseUrl}/clips/${clipId}/download`;

    const response = await fetch(url, {
      headers: await this.getHeaders(userId),
    });

    if (!response.ok) {
      throw new Error(`Failed to download clip: ${response.statusText}`);
    }

    return response.blob();
  }

  /**
   * Get clip video URL for preview
   */
  getClipUrl(filename: string): string {
    return `${this.baseUrl}/clips/${filename}`;
  }

  // ==================== HEALTH ====================

  /**
   * Check API health
   */
  async healthCheck(): Promise<{ status: string; database: string }> {
    const response = await fetch(`${this.baseUrl}/health/db`);
    if (!response.ok) {
      throw new Error('API health check failed');
    }
    return response.json();
  }
}

export const api = new ViraClipAPI();
