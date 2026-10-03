import { declareIndexPlugin, type ReactRNPlugin, WidgetLocation } from '@remnote/plugin-sdk';
import {
  DEFAULT_API_URL,
  POWERUP,
  SETTING_API_URL,
  SETTING_DIRECTION,
  SETTING_INTERVAL,
  SETTING_LINK_EXISTING,
  SLOT_WORD_ID,
} from '../constants';
import { watchForChanges } from '../live';
import { describeSync, linkExistingFlashcards, syncNow } from '../sync';

let timer: ReturnType<typeof setInterval> | undefined;
let stopWatching: (() => void) | undefined;

async function syncAndReport(plugin: ReactRNPlugin, { quiet }: { quiet: boolean }) {
  try {
    const summary = await syncNow(plugin);
    // Background runs stay silent unless something happened or went wrong.
    if (!quiet || summary.error || summary.created || summary.removed || summary.disabled || summary.enabled) {
      await plugin.app.toast(describeSync(summary));
    }
  } catch (error) {
    if (!quiet) await plugin.app.toast(error instanceof Error ? error.message : String(error));
  }
}

async function onActivate(plugin: ReactRNPlugin) {
  await plugin.settings.registerDropdownSetting({
    id: SETTING_DIRECTION,
    title: 'Card direction for new words',
    defaultValue: 'both',
    options: [
      { key: 'both', value: 'both', label: 'Both directions' },
      { key: 'forward', value: 'forward', label: 'Word → translation' },
      { key: 'backward', value: 'backward', label: 'Translation → word' },
    ],
  });
  await plugin.settings.registerBooleanSetting({
    id: SETTING_LINK_EXISTING,
    title: 'Use flashcards I already have',
    description: 'When a new Langfour word already has a flashcard anywhere in RemNote, link it instead of creating a duplicate. Its reviews then count in Langfour.',
    defaultValue: true,
  });
  await plugin.settings.registerNumberSetting({
    id: SETTING_INTERVAL,
    title: 'Sync every N minutes while RemNote is open (0 = only on start and on demand)',
    defaultValue: 60,
  });
  await plugin.settings.registerStringSetting({
    id: SETTING_API_URL,
    title: 'Langfour API URL',
    description: 'Change only when running the API locally.',
    defaultValue: DEFAULT_API_URL,
  });

  await plugin.app.registerPowerup({
    name: 'Langfour word',
    code: POWERUP,
    description: 'A word synced from Langfour. Its reviews are reported back to Langfour.',
    options: {
      slots: [
        { code: SLOT_WORD_ID, name: 'Langfour word id', onlyProgrammaticModifying: true, hidden: true },
      ],
    },
  });

  await plugin.app.registerWidget('progress', WidgetLocation.Pane, {
    dimensions: { height: 'auto', width: '100%' },
    widgetTabTitle: 'Langfour progress',
  });

  await plugin.app.registerCommand({
    id: 'langfour-sync',
    name: 'Langfour: Sync now',
    action: () => syncAndReport(plugin, { quiet: false }),
  });
  await plugin.app.registerCommand({
    id: 'langfour-link-existing',
    name: 'Langfour: Link existing flashcards',
    action: async () => {
      try {
        const moved = await linkExistingFlashcards(plugin);
        await plugin.app.toast(
          moved
            ? `Langfour: ${moved} word${moved === 1 ? '' : 's'} now use your existing flashcards; the duplicates were removed.`
            : 'Langfour: no duplicates of your existing flashcards found.',
        );
      } catch (error) {
        await plugin.app.toast(error instanceof Error ? error.message : String(error));
      }
    },
  });
  // Connecting happens on the progress page. Opened from this command, it
  // asks for a pairing code straight away instead of offering a button first.
  await plugin.app.registerCommand({
    id: 'langfour-connect',
    name: 'Langfour: Connect',
    action: async () => {
      await plugin.window.openWidgetInPane('progress', { connect: true });
    },
  });
  await plugin.app.registerCommand({
    id: 'langfour-progress',
    name: 'Langfour: Open progress',
    action: async () => {
      await plugin.window.openWidgetInPane('progress');
    },
  });

  const minutes = Number(await plugin.settings.getSetting<number>(SETTING_INTERVAL)) || 0;
  if (minutes > 0) {
    timer = setInterval(() => syncAndReport(plugin, { quiet: true }), minutes * 60_000);
  }

  // In the background: RemNote finishes loading the plugin only once
  // onActivate returns. Sync after RemNote has loaded the knowledge base;
  // before that, Rems that exist but have not arrived yet would look deleted.
  // Answers and turned-off cards are sent as they happen from then on.
  void plugin.app.waitForInitialSync().then(() => {
    stopWatching = watchForChanges(plugin);
    return syncAndReport(plugin, { quiet: true });
  });
}

async function onDeactivate(_: ReactRNPlugin) {
  if (timer) clearInterval(timer);
  stopWatching?.();
}

declareIndexPlugin(onActivate, onDeactivate);
