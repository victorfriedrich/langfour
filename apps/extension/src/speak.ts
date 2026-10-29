import { requestBackend } from './api-service';

// Pronunciation from /api/tts (ElevenLabs, keyed on the server). The audio is
// decoded with Web Audio rather than played from a data: URL in an <audio>
// element, which the host page's media-src CSP would apply to.

let context: AudioContext | null = null;
// Per page: a word heard once is not paid for or fetched again.
const decoded = new Map<string, Promise<AudioBuffer>>();

function fetchAudio(text: string, language: string, ctx: AudioContext): Promise<AudioBuffer> {
  const key = `${language}:${text.toLowerCase()}`;
  let pending = decoded.get(key);
  if (!pending) {
    pending = requestBackend('/api/tts', { text, language }).then((response) => {
      if (!response.ok) throw new Error(`Speech failed: ${response.status} ${response.statusText}`);
      const { audio } = JSON.parse(response.body) as { audio: string };
      const bytes = Uint8Array.from(atob(audio), (c) => c.charCodeAt(0));
      return ctx.decodeAudioData(bytes.buffer);
    });
    // A failure should be retried on the next tap, not remembered.
    pending.catch(() => decoded.delete(key));
    decoded.set(key, pending);
  }
  return pending;
}

export async function speak(text: string, language: string): Promise<void> {
  // Created inside the click, so the page's autoplay policy lets it play.
  context ??= new AudioContext();
  await context.resume();
  const buffer = await fetchAudio(text.trim(), language, context);
  const source = context.createBufferSource();
  source.buffer = buffer;
  source.connect(context.destination);
  source.start();
}

/** Wires a speaker button: plays the text and shows when it is loading. */
export function attachSpeakButton(button: HTMLElement, text: string, language: string): void {
  button.addEventListener('click', (event) => {
    event.stopPropagation();
    button.classList.add('speaking');
    speak(text, language)
      .catch((error) => console.error('Speech error:', error))
      .finally(() => button.classList.remove('speaking'));
  });
}

export const SPEAKER_ICON =
  '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 5 6 9H2v6h4l5 4V5z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M19 5a10 10 0 0 1 0 14"/></svg>';
