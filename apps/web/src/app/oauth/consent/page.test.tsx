import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UserContext } from '@/context/UserContext';
import ConsentPage from './page';

const mocks = vi.hoisted(() => ({
  get: vi.fn(), approve: vi.fn(), deny: vi.fn(), push: vi.fn(), remember: vi.fn(),
  params: new URLSearchParams('authorization_id=request-a&redirect_uri=https://evil.example'),
}));
vi.mock('@/lib/supabaseclient', () => ({ supabase: { auth: { oauth: {
  getAuthorizationDetails: mocks.get, approveAuthorization: mocks.approve, denyAuthorization: mocks.deny,
} } } }));
vi.mock('@/lib/afterLogin', () => ({ rememberAfterLogin: mocks.remember }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: mocks.push }), useSearchParams: () => mocks.params }));

const details = {
  authorization_id: 'request-a', client: { name: 'Test AI' },
  redirect_uri: 'https://client.example/callback', scope: 'email', user: { email: 'learner@example.com' },
};
function renderPage(anonymous = false) {
  return render(<UserContext.Provider value={{
    user: { id: 'user-a', is_anonymous: anonymous }, loading: false,
  } as React.ContextType<typeof UserContext>}><ConsentPage /></UserContext.Provider>);
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.params = new URLSearchParams('authorization_id=request-a&redirect_uri=https://evil.example');
  mocks.get.mockResolvedValue({ data: details, error: null });
  mocks.approve.mockResolvedValue({ data: { redirect_url: 'https://client.example/callback?code=approved' }, error: null });
  mocks.deny.mockResolvedValue({ data: { redirect_url: 'https://client.example/callback?error=access_denied' }, error: null });
});

describe('OAuth consent', () => {
  it('loads verified client details, then waits for explicit approval', async () => {
    const assign = vi.spyOn(window.location, 'assign').mockImplementation(() => {});
    renderPage();
    expect(await screen.findByText('Test AI')).toBeInTheDocument();
    expect(screen.getByText(/client.example/)).toBeInTheDocument();
    expect(screen.queryByText(/evil.example/)).not.toBeInTheDocument();
    expect(mocks.approve).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Allow access' }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith('https://client.example/callback?code=approved'));
    expect(mocks.approve).toHaveBeenCalledWith('request-a', { skipBrowserRedirect: true });
    assign.mockRestore();
  });

  it('returns a denied grant to the client', async () => {
    const assign = vi.spyOn(window.location, 'assign').mockImplementation(() => {});
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: 'Deny' }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith('https://client.example/callback?error=access_denied'));
    expect(mocks.approve).not.toHaveBeenCalled();
    assign.mockRestore();
  });

  it('requires a real login and preserves the authorization request', () => {
    renderPage(true);
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(mocks.remember).toHaveBeenCalledWith('/oauth/consent?authorization_id=request-a');
    expect(mocks.push).toHaveBeenCalledWith('/login');
    expect(mocks.get).not.toHaveBeenCalled();
  });

  it('handles already-consented redirects returned by Supabase', async () => {
    const assign = vi.spyOn(window.location, 'assign').mockImplementation(() => {});
    mocks.get.mockResolvedValue({ data: { redirect_url: 'https://client.example/callback?code=existing' }, error: null });
    renderPage();
    await waitFor(() => expect(assign).toHaveBeenCalledWith('https://client.example/callback?code=existing'));
    expect(mocks.approve).not.toHaveBeenCalled();
    assign.mockRestore();
  });

  it('shows expired or failed requests without an approval button', async () => {
    mocks.get.mockResolvedValue({ data: null, error: { message: 'Expired' } });
    renderPage();
    expect(await screen.findByRole('alert')).toHaveTextContent('Start again');
    expect(screen.queryByRole('button', { name: 'Allow access' })).not.toBeInTheDocument();
  });

  it('does not fetch or approve when authorization_id is missing', () => {
    mocks.params = new URLSearchParams();
    renderPage();
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(mocks.get).not.toHaveBeenCalled();
  });

  it('reports a failed decision without redirecting', async () => {
    const assign = vi.spyOn(window.location, 'assign').mockImplementation(() => {});
    mocks.approve.mockRejectedValue(new Error('Network error'));
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: 'Allow access' }));
    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(assign).not.toHaveBeenCalled();
    assign.mockRestore();
  });
});
