import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import DashboardPage from '../app/dashboard/page';

describe('DashboardPage', () => {
  it('renders sidebar navigation', () => {
    render(<DashboardPage />);
    expect(screen.getByText(/Dashboard/i)).toBeInTheDocument();
    expect(screen.getByText(/My Clips/i)).toBeInTheDocument();
    expect(screen.getByText(/Analytics/i)).toBeInTheDocument();
    expect(screen.getByText(/Settings/i)).toBeInTheDocument();
    expect(screen.getByText(/Sign Out/i)).toBeInTheDocument();
  });

  it('renders header with new project button', () => {
    render(<DashboardPage />);
    expect(screen.getByText(/New Project/i)).toBeInTheDocument();
  });

  it('renders stats cards', () => {
    render(<DashboardPage />);
    expect(screen.getByText(/Total Clips/i)).toBeInTheDocument();
    expect(screen.getByText(/Projects/i)).toBeInTheDocument();
    expect(screen.getByText(/Viral Score/i)).toBeInTheDocument();
    expect(screen.getByText(/Time Saved/i)).toBeInTheDocument();
  });

  it('renders recent projects section', () => {
    render(<DashboardPage />);
    expect(screen.getByText(/Recent Projects/i)).toBeInTheDocument();
    expect(screen.getByText(/View All/i)).toBeInTheDocument();
  });

  it('renders project cards with status indicators', () => {
    render(<DashboardPage />);
    // Check for sample project titles from the mock data
    expect(screen.getByText(/Podcast Episode/i)).toBeInTheDocument();
    expect(screen.getByText(/Tutorial: React Hooks/i)).toBeInTheDocument();
  });

  it('renders quick actions section', () => {
    render(<DashboardPage />);
    expect(screen.getByText(/Upload Video/i)).toBeInTheDocument();
    expect(screen.getByText(/AI Templates/i)).toBeInTheDocument();
    expect(screen.getByText(/Analytics/i)).toBeInTheDocument();
  });

  it('renders ViraClip logo', () => {
    render(<DashboardPage />);
    expect(screen.getByText(/ViraClip/i)).toBeInTheDocument();
  });
});
