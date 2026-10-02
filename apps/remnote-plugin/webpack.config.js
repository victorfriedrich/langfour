// Adapted from remnoteio/remnote-plugin-template-react. RemNote loads each
// widget twice: `<name>.js` for native mode and `<name>-sandbox.js` inside the
// iframe that index.html sets up, so every file in src/widgets gets both.
const { resolve, relative } = require('path');
const { globSync } = require('glob');
const HtmlWebpackPlugin = require('html-webpack-plugin');
const { EsbuildPlugin } = require('esbuild-loader');
const { ProvidePlugin, BannerPlugin } = require('webpack');
const MiniCssExtractPlugin = require('mini-css-extract-plugin');
const CopyPlugin = require('copy-webpack-plugin');

const isProd = process.env.NODE_ENV === 'production';
const SANDBOX_SUFFIX = '-sandbox';

const entry = {};
for (const file of globSync('./src/widgets/**/*.tsx')) {
  const name = relative('src/widgets', file).replace(/\.tsx$/, '').replace(/\\/g, '/');
  entry[name] = `./${file}`;
  entry[`${name}${SANDBOX_SUFFIX}`] = `./${file}`;
}

module.exports = {
  mode: isProd ? 'production' : 'development',
  entry,
  output: { path: resolve(__dirname, 'dist'), filename: '[name].js', publicPath: '' },
  resolve: { extensions: ['.js', '.jsx', '.ts', '.tsx'] },
  module: {
    rules: [
      { test: /\.[jt]sx?$/, loader: 'esbuild-loader', options: { loader: 'tsx', target: 'es2020' } },
      {
        test: /\.css$/i,
        use: [isProd ? MiniCssExtractPlugin.loader : 'style-loader', { loader: 'css-loader', options: { url: false } }],
      },
    ],
  },
  plugins: [
    isProd && new MiniCssExtractPlugin({ filename: '[name].css' }),
    new HtmlWebpackPlugin({
      filename: 'index.html',
      inject: false,
      templateContent: `
      <body></body>
      <script type="text/javascript">
      const widgetName = new URLSearchParams(window.location.search).get("widgetName");
      if (!widgetName) { document.body.innerHTML += "Widget ID not specified."; }
      const s = document.createElement("script");
      s.type = "module";
      s.src = widgetName + "${SANDBOX_SUFFIX}.js";
      document.body.appendChild(s);
      </script>`,
    }),
    new ProvidePlugin({ React: 'react', reactDOM: 'react-dom' }),
    new BannerPlugin({
      banner: (file) => (file.chunk.name.includes(SANDBOX_SUFFIX) ? '' : 'const IMPORT_META=import.meta;'),
      raw: true,
    }),
    new CopyPlugin({ patterns: [{ from: 'public', to: '' }, { from: 'README.md', to: '' }] }),
  ].filter(Boolean),
  optimization: isProd ? { minimize: true, minimizer: [new EsbuildPlugin({ target: 'es2020' })] } : undefined,
  devServer: isProd
    ? undefined
    : {
        port: 8080,
        hot: false,
        liveReload: true,
        compress: true,
        headers: { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': 'baggage, sentry-trace' },
      },
};
