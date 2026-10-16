// icons.mjs (.mjs so webpack parses the imports as ESM, package.json is commonjs) - registers the <iconify-icon> element and the Tabler icons used in the templates

import 'iconify-icon';
import { addCollection } from 'iconify-icon';

// TABLER_ICONS is filled in by webpack (see webpack.config.js) with only the
// icons referenced as "tabler:<name>" in templates/ and src/js/
addCollection(TABLER_ICONS);
