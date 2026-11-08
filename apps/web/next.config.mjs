/** @type {import('next').NextConfig} */
const nextConfig = {
  eslint: {
    ignoreDuringBuilds: true,
  },
  typescript: {
    ignoreBuildErrors: true,
  },
  // Practice used to live at /vocabulary and Vocabulary at /progress. Links
  // in extensions not yet updated still point there.
  async redirects() {
    return [
      // The privacy policy and imprint live on the landing site.
      { source: '/privacy', destination: 'https://www.langfour.com/privacy', permanent: true },
      { source: '/imprint', destination: 'https://www.langfour.com/imprint', permanent: true },
      { source: '/progress', destination: '/vocabulary', permanent: true },
      // The extension's "Words you likely know" link: a list on Practice. Not
      // permanent, since /vocabulary itself is a page again.
      {
        source: '/vocabulary',
        has: [{ type: 'query', key: 'words', value: 'stuck' }],
        destination: '/practice',
        permanent: false,
      },
    ];
  },
};

export default nextConfig;
