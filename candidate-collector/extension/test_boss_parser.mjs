import assert from 'node:assert/strict';

// 推荐页简历面板的真实文本（用户提供样本）；「全文」是面板顶部标签，必须过滤
const SAMPLE = `全文
王女士 26岁 北京 在职-考虑机会
经历概览
北京三快网络科技有限公司
2024.01 - 至今
品牌营销
2年6个月
深圳市明源云科技有限公司北京分公司
2023.03 - 2024.01
市场营销策划
10个月
绿城房地产集团有限公司
2020.03 - 2023.03
品牌策划经理
3年
北京万科房地产经纪有限公司
2018.05 - 2019.09
营销策划
1年4个月
英国萨里大学
2016 - 2017
国际零售市场 • 硕士
硕士
英国德蒙福特大学
2012 - 2015
商业管理 • 本科
本科
重点阅读`;

globalThis.document = {
  body: {
    innerText: SAMPLE,
    querySelectorAll: () => []
  }
};

const boss = await import(new URL('./parsers/boss.js', import.meta.url));

const result = boss.extractBossSections();
const headings = result.sections.map(section => section.heading);

// 「经历概览」必须被识别并统一成下游认识的「工作经历」
assert.ok(headings.includes('工作经历'), 'missing 工作经历 section: ' + headings.join(','));
assert.ok(!headings.includes('经历概览'), '经历概览 should be renamed');

const work = result.sections.find(section => section.heading === '工作经历');
assert.ok(work.text.includes('北京三快网络科技有限公司'));
assert.ok(work.text.includes('2024.01 - 至今'));
assert.ok(work.text.includes('绿城房地产集团有限公司'));

// 教育内容（本科/硕士）应保留在全文里供后端解析
assert.ok(result.raw_text.includes('英国萨里大学'));
assert.ok(result.raw_text.includes('硕士'));

// 面板顶部「全文」标签不能进入任何分节（否则后端会把「全文」当成姓名）
assert.ok(!result.sections.some(section => section.heading === '全文'));
const allText = result.sections.map(section => section.text).join('\n');
assert.ok(!allText.split('\n').includes('全文'));
assert.ok(!result.raw_text.split('\n').includes('全文'));
const basic = result.sections.find(section => section.heading === '基础信息');
assert.ok(basic && basic.text.includes('王女士'));

// 没有基础信息行时也不能伪造「全文」分节
globalThis.document.body.innerText = '全文\n经历概览\n美团\n2018.10 - 至今\n产品经理\n7年';
const sparse = boss.extractBossSections();
assert.ok(!sparse.sections.some(section => section.heading === '全文'));
assert.ok(!sparse.raw_text.split('\n').includes('全文'));

console.log('boss parser overview-section tests passed');
