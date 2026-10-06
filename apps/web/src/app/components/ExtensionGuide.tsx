import { useContext, useState } from 'react';
import { motion } from 'framer-motion';
import { AlertCircle, Check, Copy, Download } from 'lucide-react';
import ExtensionDemo, { type DemoMode } from './ExtensionDemo';
import { UserContext } from '@/context/UserContext';
import { useExtensionStatus } from '../hooks/useExtensionStatus';

const DOWNLOAD_URL =
    'https://xpovcmbrttmkhnrfspvo.supabase.co/storage/v1/object/sign/downloads/dist.zip?token=eyJraWQiOiJzdG9yYWdlLXVybC1zaWduaW5nLWtleV80YzMyYTJlNC1lNDA4LTRjMTYtYTMyNC0yM2RlYTM5NzcyOGMiLCJhbGciOiJIUzI1NiJ9.eyJ1cmwiOiJkb3dubG9hZHMvZGlzdC56aXAiLCJpYXQiOjE3NjAzNzIzMTEsImV4cCI6MTc5MTkwODMxMX0.MqkevU8BErkG1-vSuW4NFGapROTBommmY16C9FeHyrU';

const DEMOS: Record<DemoMode, { label: string; caption: string }> = {
    video: {
        label: 'Subtitles',
        caption: 'For watching. Unknown words light up in YouTube, Netflix and Prime Video subtitles; hover one to translate it.',
    },
    reader: {
        label: 'Reader',
        caption: 'For reading. Press ⌘⇧Y on any article to open it in a clean page where every unknown word is one click away.',
    },
};

function CopyExtensionsUrl() {
    const [copied, setCopied] = useState(false);
    return (
        <button
            onClick={() => {
                navigator.clipboard.writeText('chrome://extensions');
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
            }}
            className="inline-flex items-center gap-1 rounded bg-gray-100 px-1.5 py-0.5 font-mono text-xs text-gray-800 hover:bg-gray-200"
        >
            chrome://extensions
            {copied ? <Check size={12} className="text-emerald-600" /> : <Copy size={12} className="text-gray-400" />}
        </button>
    );
}

export default function ExtensionGuide() {
    const [downloaded, setDownloaded] = useState(false);
    const ext = useExtensionStatus();
    const { user } = useContext(UserContext);
    const installed = ext.state === 'installed';
    const wrongAccount =
        installed && ext.signedIn && !!ext.email && !!user?.email && ext.email.toLowerCase() !== user.email.toLowerCase();

    const steps = [
        <>Unzip the downloaded <code className="rounded bg-gray-100 px-1 font-mono text-xs">dist.zip</code></>,
        <>Open <CopyExtensionsUrl /> in Chrome</>,
        <>Turn on <span className="font-medium text-gray-900">Developer mode</span> (top right)</>,
        <>Click <span className="font-medium text-gray-900">Load unpacked</span> and pick the folder, then sign in from the extension icon</>,
    ];

    return (
        <div className="min-h-screen bg-gray-50">
            <div className="max-w-3xl px-4 md:pl-10 md:pr-3 py-8 pb-16">
                <h1 className="text-2xl font-semibold text-gray-900">Langfour for Chrome</h1>
                <p className="mt-1.5 text-sm text-gray-500">Translate words and add them to your flashcards as you watch or read.</p>

                {installed ? (
                    <div className="mt-5 max-w-md rounded-xl bg-white p-4 shadow-sm ring-1 ring-gray-900/5">
                        <div className="flex items-start gap-3">
                            <span
                                className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full ${
                                    ext.signedIn && !wrongAccount ? 'bg-emerald-100 text-emerald-600' : 'bg-amber-100 text-amber-600'
                                }`}
                            >
                                {ext.signedIn && !wrongAccount ? <Check size={12} strokeWidth={3} /> : <AlertCircle size={12} strokeWidth={3} />}
                            </span>
                            <div className="text-sm">
                                <p className="font-medium text-gray-900">
                                    {!ext.signedIn
                                        ? 'Installed, not signed in'
                                        : wrongAccount
                                          ? 'Signed in with a different account'
                                          : 'Connected'}
                                </p>
                                <p className="mt-0.5 text-gray-500">
                                    {!ext.signedIn
                                        ? 'Click the Langfour icon in Chrome and sign in to start adding words.'
                                        : wrongAccount
                                          ? `The extension uses ${ext.email}; this site uses ${user?.email}. Words will go to the extension's account.`
                                          : `Adding words to ${ext.email ?? 'your account'}.`}
                                </p>
                            </div>
                        </div>
                    </div>
                ) : ext.state === 'checking' ? (
                    <div className="mt-5 h-[42px]" />
                ) : downloaded ? (
                    <motion.section
                        initial={{ opacity: 0, y: 6 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ duration: 0.25, ease: 'easeOut' }}
                        className="mt-5 hidden max-w-xl rounded-xl bg-white p-5 shadow-sm ring-1 ring-indigo-600/20 md:block"
                    >
                        <h2 className="text-base font-semibold text-gray-900">Finish installing</h2>
                        <p className="mt-0.5 text-sm text-gray-500">The download has started. Four steps in Chrome:</p>
                        <ol className="mt-4 space-y-3">
                            {steps.map((step, i) => (
                                <li key={i} className="flex items-center gap-3 text-sm text-gray-700">
                                    <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-indigo-600 text-xs font-medium text-white">
                                        {i + 1}
                                    </span>
                                    <span>{step}</span>
                                </li>
                            ))}
                        </ol>
                        <div className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-gray-100 pt-4 text-sm">
                            <button
                                type="button"
                                onClick={() => window.location.reload()}
                                className="rounded-lg bg-indigo-600 px-3.5 py-2 font-medium text-white hover:bg-indigo-700"
                            >
                                I&apos;ve installed it, reload
                            </button>
                            <a href={DOWNLOAD_URL} download="lang-extension.zip" className="text-gray-500 hover:text-gray-800">
                                Download again
                            </a>
                        </div>
                    </motion.section>
                ) : (
                    <div className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-2">
                        <a
                            href={DOWNLOAD_URL}
                            download="lang-extension.zip"
                            onClick={() => setDownloaded(true)}
                            className="hidden md:inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-indigo-700"
                        >
                            <Download size={16} />
                            Download extension
                        </a>
                        <span className="hidden md:inline text-xs text-gray-400">Free · Chrome on desktop</span>
                        <p className="md:hidden text-sm text-gray-600">Open this page on a computer with Chrome to install.</p>
                    </div>
                )}

                {(Object.keys(DEMOS) as DemoMode[]).map((key) => (
                    <section key={key} className="mt-10">
                        <h2 className="text-base font-semibold text-gray-900">{DEMOS[key].label}</h2>
                        <p className="mt-1 mb-4 max-w-xl text-sm text-gray-500">{DEMOS[key].caption}</p>
                        <ExtensionDemo mode={key} />
                    </section>
                ))}

            </div>
        </div>
    );
}
