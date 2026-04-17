import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { NeonButton } from './neon-button';

describe('NeonButton', () => {
  it('renders with primary variant by default', () => {
    render(<NeonButton>Click me</NeonButton>);
    expect(screen.getByText('Click me')).toBeInTheDocument();
  });

  it('renders with different variants', () => {
    const { rerender } = render(<NeonButton variant="primary">Primary</NeonButton>);
    expect(screen.getByText('Primary')).toBeInTheDocument();

    rerender(<NeonButton variant="ghost">Ghost</NeonButton>);
    expect(screen.getByText('Ghost')).toBeInTheDocument();

    rerender(<NeonButton variant="outline">Outline</NeonButton>);
    expect(screen.getByText('Outline')).toBeInTheDocument();
  });

  it('handles click events', () => {
    const handleClick = vi.fn();
    render(<NeonButton onClick={handleClick}>Click me</NeonButton>);
    fireEvent.click(screen.getByText('Click me'));
    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it('can be disabled', () => {
    render(<NeonButton disabled>Disabled</NeonButton>);
    expect(screen.getByText('Disabled')).toBeDisabled();
  });

  it('renders with different sizes', () => {
    const { rerender } = render(<NeonButton size="sm">Small</NeonButton>);
    expect(screen.getByText('Small')).toBeInTheDocument();

    rerender(<NeonButton size="lg">Large</NeonButton>);
    expect(screen.getByText('Large')).toBeInTheDocument();
  });

  it('renders with glowing effect', () => {
    render(<NeonButton glowing>Glowing</NeonButton>);
    const button = screen.getByText('Glowing');
    expect(button.className).toContain('animate-pulse-glow');
  });
});
