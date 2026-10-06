import { act, renderHook } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { useExtensionStatus } from './useExtensionStatus';

afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
});

it('receives sign-in changes after the handshake without polling', () => {
    vi.useFakeTimers();
    const post = vi.spyOn(window, 'postMessage').mockImplementation(() => {});
    const { result, unmount } = renderHook(() => useExtensionStatus());
    expect(post).toHaveBeenCalledTimes(1);
    act(() => vi.advanceTimersByTime(1200));
    expect(result.current.state).toBe('missing');
    const announce = (signedIn: boolean) => act(() => {
        window.dispatchEvent(new MessageEvent('message', {
            source: window,
            data: { source: 'langfour-extension', type: 'STATUS', status: {
                version: '1.2.0', signedIn, email: signedIn ? 'reader@example.com' : null,
            } },
        }));
    });
    announce(true);
    expect(result.current).toMatchObject({ state: 'installed', signedIn: true });
    act(() => vi.advanceTimersByTime(30_000));
    announce(false);
    expect(result.current).toMatchObject({ state: 'installed', signedIn: false });
    expect(post).toHaveBeenCalledTimes(1);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
});
