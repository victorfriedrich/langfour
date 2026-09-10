import { createClient, isAuthRetryableFetchError } from '@supabase/supabase-js';

const supabaseUrl = process.env.REACT_APP_SUPABASE_URL!;
const supabaseAnonKey = process.env.REACT_APP_SUPABASE_ANON_KEY!;

/**
 * `src/auth_handler.html` is listed in `web_accessible_resources` (the magic
 * link redirect is a web-origin-initiated navigation, so it has to be), and
 * the manifest pins a `key`, so the extension ID is fixed and public. That
 * combination means any page can navigate the user to our auth handler with
 * a URL of its choosing.
 *
 * Under the library default (`flowType: 'implicit'`) that was enough to hand
 * the extension someone else's session: auth-js treats a bare
 * `#access_token=...` in the URL as a completed login. PKCE closes it --
 * finishing a login additionally requires the `code_verifier` written to
 * this origin's localStorage when *we* started the flow, which a third-party
 * page cannot produce.
 */
const authOptions = {
    flowType: 'pkce',

    /**
     * Belt-and-braces on top of `flowType`. auth-js only consults this when
     * deciding whether a URL is an *implicit* callback, so returning false
     * for token-bearing URLs makes it ignore them outright rather than
     * relying on the PKCE/implicit mismatch check to reject them later.
     * Error params are still allowed through so expired-link messages keep
     * surfacing to the user.
     */
    detectSessionInUrl: (_url: URL, params: { [key: string]: string }) =>
        Boolean(params.error || params.error_description || params.error_code),
} as const;

export const supabase = createClient(supabaseUrl, supabaseAnonKey, {
    auth: authOptions,
});

type AuthData = { access_token: string; refresh_token: string };

/**
 * Makes sure the Supabase client has a session, hydrating it from authData
 * if needed. Returns whether a session is actually available afterwards, so
 * callers can distinguish "no session" from a successful no-op.
 */
export async function ensureSupabaseSession(authData?: AuthData | null): Promise<boolean> {
    // Check if there is an existing session
    const { data: { session }, error } = await supabase.auth.getSession();

    if (error) {
        console.error('Error fetching session:', error.message);
        return false;
    }

    if (session) {
        return true;
    }

    if (!authData?.access_token || !authData?.refresh_token) {
        console.warn('No existing Supabase session and no auth data to create one from');
        return false;
    }

    // Create a new session using the provided access token
    const { access_token, refresh_token } = authData;
    const { error: sessionError } = await supabase.auth.setSession({
        access_token,
        refresh_token,
    });

    if (sessionError) {
        // A transient network failure says nothing about whether the stored
        // session is still good, so keep it and let the next wake-up retry.
        if (isAuthRetryableFetchError(sessionError)) {
            console.warn('Could not reach Supabase to restore session:', sessionError.message);
            return false;
        }

        // Anything else means GoTrue rejected these tokens outright -- most
        // often `session_not_found` (surfaced as AuthSessionMissingError)
        // after a sign-out, since `signOut()` defaults to global scope and
        // revokes the session server-side.
        //
        // `supabaseSession` is a snapshot: AUTH_SUCCESS writes it, the
        // background rewrites it after a token refresh, and only the content
        // script's `logout` DOM listener and the popup's sign-out remove it.
        // Nothing else clears it, so without this the
        // service worker replays the same dead tokens on every wake-up and
        // logs the same error forever. Drop it so the extension fails as
        // "signed out" rather than "permanently broken".
        console.warn('Stored Supabase session is no longer valid, discarding:', sessionError.message);
        await chrome.storage.local.remove('supabaseSession');
        return false;
    }

    return true;
}
/**
 * Returns an access token the backend will accept, or null when the user is
 * signed out. Restores the session from chrome.storage first (the service
 * worker's client keeps its session in memory only, so a worker restart
 * loses it), then relies on auth-js to refresh: both `setSession` and
 * `getSession` exchange the refresh token for a new access token when the
 * current one is expired or about to expire.
 */
export async function getAccessToken(): Promise<string | null> {
    const { supabaseSession } = await chrome.storage.local.get('supabaseSession');
    if (!(await ensureSupabaseSession(supabaseSession))) {
        return null;
    }

    const { data: { session }, error } = await supabase.auth.getSession();
    if (error) {
        console.error('Error fetching session for backend call:', error.message);
        return null;
    }
    return session?.access_token ?? null;
}
