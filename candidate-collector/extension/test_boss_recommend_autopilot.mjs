import assert from 'node:assert/strict';

await import(new URL('./content/boss_recommend_autopilot.js?test=' + Date.now(), import.meta.url));
const api = globalThis.__OT_BOSS_RECOMMEND_AUTOPILOT__;

assert.ok(api);
assert.equal(api.isRecommendPage('/web/chat/recommend'), true);
assert.equal(api.isRecommendPage('/web/chat/recommend?ka=1'), true);
assert.equal(api.isRecommendPage('/web/chat/index'), false);
assert.equal(api.isRecommendPage('/web/geek/job'), false);

// 推荐卡片：有身份线索 → 是候选人
assert.equal(api.isCandidateCardText('张先生 28岁 5年 本科 在职-考虑机会'), true);
assert.equal(api.isCandidateCardText('李女士 硕士 3年经验 离职-随时到岗'), true);
// 太短 / 太长 → 拒绝
assert.equal(api.isCandidateCardText('本科'), false);
assert.equal(api.isCandidateCardText(('很长'.repeat(500)) + '28岁 本科'), false);
// 非候选人入口 → 拒绝
assert.equal(api.isCandidateCardText('下载App 登录 注册 28岁 本科'), false);
// 公司卡片：只有成立年限、带公司后缀 → 拒绝
assert.equal(api.isCandidateCardText('北京三快网络科技有限公司 10年 上市公司'), false);
assert.equal(api.isCandidateCardText('某科技集团 15年 万人规模'), false);
// 只有年限没有年龄/学历 → 拒绝（年限是公司/职位属性）
assert.equal(api.isCandidateCardText('高级产品经理 8年 3万-5万'), false);
// 已展开的简历抽屉（≥2 个分节标题）→ 拒绝，交给 auto_import 桥接
assert.equal(
  api.isCandidateCardText('王先生 30岁 本科 工作经历 阿里巴巴 教育经历 浙江大学'),
  false
);

// 风控文案检测
assert.equal(api.detectRiskControl('请完成安全验证后继续'), true);
assert.equal(api.detectRiskControl('访问过于频繁，请稍后再试'), true);
assert.equal(api.detectRiskControl('正常推荐列表内容'), false);

// 卡片去重键
assert.equal(api.cardKey('https://www.zhipin.com/geek/abc#x', '张三 28岁'), 'href|https://www.zhipin.com/geek/abc');
assert.equal(api.cardKey('', '张三 28岁 本科'), api.cardKey('', '张三 28岁 本科'));
assert.notEqual(api.cardKey('', '张三 28岁'), api.cardKey('', '李四 30岁'));

// 入库结果分类
assert.equal(api.classifyImportMessage('候选人资料已保存本地并完成自动入库'), 'imported');
assert.equal(api.classifyImportMessage('已写入云端人才库'), 'imported');
assert.equal(api.classifyImportMessage('候选人资料读取失败：x'), 'failed');
assert.equal(api.classifyImportMessage('空闲'), '');

// 状态归一化：跨天清零今日计数
const yesterday = api.normalizeState({
  enabled: true,
  day: '2026-07-28',
  processedToday: 12,
  importedToday: 9,
  failedToday: 3,
  totalProcessed: 100,
  processedKeys: ['a']
});
assert.equal(yesterday.processedToday, 0);
assert.equal(yesterday.importedToday, 0);
assert.equal(yesterday.failedToday, 0);
assert.equal(yesterday.totalProcessed, 100);
assert.deepEqual(yesterday.processedKeys, ['a']);
assert.equal(yesterday.enabled, true);

const sameDay = api.normalizeState({
  day: yesterday.day,
  processedToday: 5,
  processedKeys: 'oops'
});
assert.equal(sameDay.processedToday, 5);
assert.deepEqual(sameDay.processedKeys, []);

console.log('boss recommend autopilot tests passed');
