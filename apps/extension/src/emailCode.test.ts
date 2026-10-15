import { describe, expect, it, vi } from 'vitest';
import { findEmailCode } from './emailCode';

// emailCode.ts signs in through the shared client; none of that runs here.
vi.mock('./supabaseclient', () => ({ supabase: {} }));

describe('findEmailCode', () => {
  it('takes the code alone, with or without spaces', () => {
    expect(findEmailCode('482913')).toBe('482913');
    expect(findEmailCode(' 482 913 ')).toBe('482913');
  });

  it('finds the code in a pasted subject line or email', () => {
    expect(findEmailCode('482913 is your Langfour code')).toBe('482913');
    expect(findEmailCode('Sign in\nOr enter this code in the Langfour extension:\n48291307\nThe link expires in 1 hour.')).toBe('48291307');
  });

  it('ignores digit runs that are too short or too long', () => {
    expect(findEmailCode('Expires in 60 minutes')).toBeNull();
    expect(findEmailCode('Order 123456789012')).toBeNull();
  });
});
