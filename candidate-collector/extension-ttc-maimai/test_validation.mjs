import assert from 'assert';
import { validatePayload } from './validation.js';

// BOSS detail page with structured sections.
const bossPayload = {
  text: 'a'.repeat(100),
  platform: 'boss',
  structured_data: {
    sections: [
      { heading: '工作经历', text: '...' },
      { heading: '教育经历', text: '...' },
    ],
  },
};
const bossChecks = validatePayload(bossPayload);
assert.strictEqual(bossChecks.ok, true);
assert.strictEqual(bossChecks.hasText, true);
assert.strictEqual(bossChecks.hasWorkExperience, true);
assert.strictEqual(bossChecks.hasEducationExperience, true);

// Empty BOSS page.
const emptyChecks = validatePayload({ text: '', platform: 'boss', structured_data: null });
assert.strictEqual(emptyChecks.ok, false);
assert.strictEqual(emptyChecks.hasText, false);
assert.strictEqual(emptyChecks.hasStructuredData, false);

// Maimai list page with candidate links.
const maimaiChecks = validatePayload({
  text: 'a'.repeat(100),
  platform: 'maimai',
  structured_data: { sections: [] },
  links: [{ url: 'https://maimai.cn/1', label: '候选人1' }],
});
assert.strictEqual(maimaiChecks.hasCandidateLinks, true);

// Liepin list page without links.
const liepinChecks = validatePayload({
  text: 'a'.repeat(100),
  platform: 'liepin',
  structured_data: { sections: [] },
  links: [],
});
assert.strictEqual(liepinChecks.hasCandidateLinks, false);

console.log('validation tests passed');
