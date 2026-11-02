// Injected into the MAIN world of www.youtube.com (contentScript.ts): the
// Favourite button and Langfour tab on channel pages (youtubeChannel.ts).
// Desktop only, like the Bookmark button it replaces.

import { addChannelCoreWords, getChannel, setChannelFavourite } from './api-service';
import type { Prefs } from './contentScript';
import { toLanguage, type Language } from './languages';
import { mountChannelPage, unmount, type ChannelApi } from './youtubeChannel';

(() => {
  if (location.host !== 'www.youtube.com') return;

  const api: ChannelApi = {
    view: getChannel,
    favourite: setChannelFavourite,
    addCoreWords: addChannelCoreWords,
    signIn: () => document.dispatchEvent(new CustomEvent('open-sign-in')),
  };

  let language: Language | null = null;
  const run = () => {
    if (language) void mountChannelPage(document, location.pathname, language, api);
    else unmount(document);
  };

  // The content script sends prefs when this script has loaded and again
  // whenever they change.
  document.addEventListener('prefs', ((event: CustomEvent<Prefs>) => {
    const next = toLanguage(event.detail?.preferredLanguage);
    if (next === language) return;
    language = next;
    run();
  }) as EventListener);
  window.addEventListener('yt-navigate-finish', run);
})();
