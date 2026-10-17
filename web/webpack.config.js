const fs = require('fs');
const path = require('path');
const webpack = require('webpack');
const MiniCssExtractPlugin = require('mini-css-extract-plugin');
const { WebpackManifestPlugin } = require('webpack-manifest-plugin');
const { getIcons } = require('@iconify/utils');
const tabler = require('@iconify-json/tabler/icons.json');

// Folders scanned for "tabler:<name>" so only the icons we actually use get
// bundled (the full Tabler set is ~2MB of JSON).
const ICON_SOURCES = [
  path.resolve(__dirname, 'templates'),
  path.resolve(__dirname, 'src/js')
];

function usedTablerIcons() {
  const names = new Set();
  for (const dir of ICON_SOURCES) {
    for (const file of fs.readdirSync(dir)) {
      if (!/\.(html|js)$/.test(file)) continue;
      const text = fs.readFileSync(path.join(dir, file), 'utf-8');
      for (const match of text.matchAll(/tabler:([a-z0-9-]+)/g)) names.add(match[1]);
    }
  }
  const icons = getIcons(tabler, [...names]);
  const missing = [...names].filter(name => !icons || !(name in icons.icons || name in (icons.aliases || {})));
  if (missing.length) console.warn(`[icons] unknown Tabler icons: ${missing.join(', ')}`);
  return icons || { prefix: 'tabler', icons: {} };
}

module.exports = {
  mode: 'production',

  entry: {
    stylecss: './src/css/style.css',
    signincss: './src/css/sign-in.css',
    trackercss: './src/css/tracker.css',
    privacycss: './src/css/privacy.css',
    termscss: './src/css/terms.css',

    icons: './src/js/icons.mjs',
    tracker: './src/js/tracker.js',
    navbar: './src/js/navbar.js'
  },

  output: {
    filename: 'chunks/[contenthash].js',
    chunkFilename: 'chunks/[contenthash].js',
    path: path.resolve(__dirname, 'static'),
    publicPath: '/static/',
    clean: true
  },

  module: {
    rules: [
      {
        test: /\.m?js$/,
        include: [path.resolve(__dirname, 'src/js')],
        use: {
          loader: 'babel-loader',
          options: {
            presets: ['@babel/preset-env'],
            sourceType: 'module'
          }
        }
      },
      {
        test: /\.css$/i,
        use: [MiniCssExtractPlugin.loader, 'css-loader']
      },
      {
        test: /\.(png|jpe?g|gif|webp|svg)$/i,
        type: 'asset/resource',
        generator: {
          filename: 'media/[name].[contenthash][ext]'
        }
      },
      {
        test: /\.(ttf|otf|woff2?)$/i,
        type: 'asset/resource',
        generator: {
          filename: 'fonts/[name].[contenthash][ext]'
        }
      }
    ]
  },

  resolve: {
    extensions: ['.js', '.mjs', '.json']
  },

  optimization: {
    splitChunks: false
  },

  plugins: [
    // Recomputed whenever a template or JS file changes, so `npm run watch`
    // picks up newly used icons without a restart.
    new webpack.DefinePlugin({
      TABLER_ICONS: webpack.DefinePlugin.runtimeValue(
        () => JSON.stringify(usedTablerIcons()),
        { contextDependencies: ICON_SOURCES }
      )
    }),
    new MiniCssExtractPlugin({
      filename: 'css/[contenthash].css',
      chunkFilename: 'css/[contenthash].css'
    }),
    new WebpackManifestPlugin({
      fileName: 'manifest.json',
      publicPath: '/static/',
      writeToFileEmit: true
    })
  ]
};
