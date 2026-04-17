import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import LandingPage from '../app/page';

describe('LandingPage', () => {
  it('renders hero section with correct heading', () => {
    render(<LandingPage />);
    expect(screen.getByText(/Turn Long Videos into/i)).toBeInTheDocument();
    expect(screen.getByText(/Viral Shorts/i)).toBeInTheDocument();
  });

  it('renders CTA buttons', () => {
    render(<LandingPage />);
    expect(screen.getByText(/Start Creating Free/i)).toBeInTheDocument();
    expect(screen.getByText(/Watch Demo/i)).toBeInTheDocument();
  });

  it('renders feature cards', () => {
    render(<LandingPage />);
    expect(screen.getByText(/AI Clip Detection/i)).toBeInTheDocument();
    expect(screen.getByText(/Smart Subtitles/i)).toBeInTheDocument();
    expect(screen.getByText(/B-Roll & Music/i)).toBeInTheDocument();
    expect(screen.getByText(/One-Click Magic/i)).toBeInTheDocument();
  });

  it('renders stats section', () => {
    render(<LandingPage />);
    expect(screen.getByText(/10x/i)).toBeInTheDocument();
    expect(screen.getByText(/Faster Editing/i)).toBeInTheDocument();
    expect(screen.getByText(/Self-Hosted/i)).toBeInTheDocument();
  });

  it('renders navigation links', () => {
    render(<LandingPage />);
    expect(screen.getByText(/Features/i)).toBeInTheDocument();
    expect(screen.getByText(/How it Works/i)).toBeInTheDocument();
    expect(screen.getByText(/Pricing/i)).toBeInTheDocument();
  });

  it('renders pricing section', () => {
    render(<LandingPage />);
    expect(screen.getByText(/Open Source/i)).toBeInTheDocument();
    expect(screen.getByText(/Cloud Hosted/i)).toBeInTheDocument();
    expect(screen.getByText(/Free/i)).toBeInTheDocument();
  });
});
