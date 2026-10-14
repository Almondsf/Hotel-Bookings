import { describe, expect, it } from 'vitest';

import { ApiError } from '../api/client';
import { addDays, formatMoney, humanize } from './format';

describe('format', () => {
  it('formats naira', () => {
    expect(formatMoney('53750')).toContain('53,750.00');
    expect(formatMoney(null)).toBe('—');
  });

  it('adds days across month ends without timezone drift', () => {
    expect(addDays('2026-01-31', 1)).toBe('2026-02-01');
    expect(addDays('2026-12-31', 1)).toBe('2027-01-01');
  });

  it('humanizes enum values', () => {
    expect(humanize('CHECKED_IN')).toBe('Checked in');
  });
});

describe('ApiError', () => {
  it('prefers the error message and exposes field errors', () => {
    const error = new ApiError(400, { check_out_date: ['Check-out date must be after check-in date.'] });
    expect(error.fieldErrors()).toEqual({ check_out_date: 'Check-out date must be after check-in date.' });
    expect(new ApiError(409, { error: 'Room 101 is not available.' }).message).toBe('Room 101 is not available.');
  });
});
