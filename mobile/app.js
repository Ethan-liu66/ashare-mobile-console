if (window.location.protocol === "file:") {
  const params = new URLSearchParams(window.location.search);
  const stock = params.get("stock");
  const target = new URL("http://localhost:4173/");
  if (stock) {
    target.searchParams.set("stock", stock);
  }
  target.searchParams.set("from", "file");
  window.location.replace(target.toString());
}

const stocks = [
  {
    code: "300750",
    name: "宁德时代",
    industry: "动力电池",
    setup: "突破后回踩不破平台，等待低位回收",
    setupType: "流动性买点",
    price: 178.6,
    trigger: 181.2,
    invalid: 167.2,
    trend: [151, 155, 158, 162, 168, 174, 182, 188, 184, 179, 176, 178, 181],
    scores: {
      "基本面与扩产质量": 24,
      "行业/主线景气度": 16,
      "趋势强度": 16,
      "回调买点质量": 14,
      "估值与风险收益比": 6,
    },
    capacity: {
      stage: "产能释放期",
      signals: [
        "扩产投入已转向产能爬坡，营收承接能力优先于短期利润波动。",
        "若毛利率企稳且库存周转改善，利润弹性会重新释放。",
        "继续观察价格战和海外订单，防止扩产变成行业供给压力。",
      ],
    },
    buySignals: [
      "主升后回调未跌回前期平台核心区。",
      "缩量回踩 MA20 附近，卖压暂未扩散。",
      "低位回收后仍需等待回踩承接，不能把追高价当成加仓指令。",
    ],
  },
  {
    code: "300308",
    name: "中际旭创",
    industry: "光模块",
    setup: "强趋势回踩 20 日线，等待抛压衰竭",
    setupType: "流动性买点",
    price: 132.4,
    trigger: 136.8,
    invalid: 124.5,
    trend: [92, 98, 104, 112, 121, 130, 142, 151, 146, 137, 130, 132, 136],
    scores: {
      "基本面与扩产质量": 26,
      "行业/主线景气度": 18,
      "趋势强度": 17,
      "回调买点质量": 13,
      "估值与风险收益比": 5,
    },
    capacity: {
      stage: "扩产投入期",
      signals: [
        "资本开支上行会压制当期利润率，但若订单饱满，不能简单扣死。",
        "重点看新产能爬坡速度、客户认证和应收账款质量。",
        "估值较敏感，业绩兑现不及预期时回撤会放大。",
      ],
    },
    buySignals: [
      "高位回调后不再创新低，只代表抛压放缓，仍需回收确认。",
      "当前更适合等重新站回短期均线。",
      "失效位明确，跌破说明调整级别扩大。",
    ],
  },
  {
    code: "002594",
    name: "比亚迪",
    industry: "新能源车",
    setup: "趋势修复中，买点未完全确认",
    setupType: "观察",
    price: 231.8,
    trigger: 244.0,
    invalid: 219.5,
    trend: [210, 214, 219, 224, 236, 241, 238, 232, 225, 228, 231, 233, 232],
    scores: {
      "基本面与扩产质量": 21,
      "行业/主线景气度": 12,
      "趋势强度": 12,
      "回调买点质量": 9,
      "估值与风险收益比": 7,
    },
    capacity: {
      stage: "扩产消化期",
      signals: [
        "规模扩张会带来折旧、渠道和价格压力，短期利润波动可解释。",
        "若行业竞争继续压价，扩产质量要下调。",
        "需要看到利润率企稳或出口增量承接。",
      ],
    },
    buySignals: [
      "尚未形成明显高低点抬升。",
      "突破确认前只适合观察，不宜提前重仓。",
      "回到平台上沿后只评估趋势修复，低位买点已过期则等待回踩。",
    ],
  },
  {
    code: "601899",
    name: "紫金矿业",
    industry: "有色金属",
    setup: "趋势保持，但离支撑偏远",
    setupType: "趋势持有",
    price: 18.26,
    trigger: 18.7,
    invalid: 16.9,
    trend: [13.4, 13.9, 14.6, 15.5, 16.2, 17.1, 18.4, 19.0, 18.3, 17.9, 18.1, 18.4, 18.26],
    scores: {
      "基本面与扩产质量": 23,
      "行业/主线景气度": 17,
      "趋势强度": 15,
      "回调买点质量": 11,
      "估值与风险收益比": 7,
    },
    capacity: {
      stage: "资源扩张期",
      signals: [
        "矿山扩张通常先体现资本开支和折旧，利润释放取决于金属价格。",
        "资源储量、项目投产节奏和商品价格要合并判断。",
        "若价格周期向下，扩产会被市场重新定价。",
      ],
    },
    buySignals: [
      "中期趋势仍强于多数周期品种。",
      "当前距失效位不算近，追买性价比一般。",
      "更理想的位置是缩量回踩后重新转强。",
    ],
  },
];

const weights = {
  "基本面与扩产质量": 30,
  "行业/主线景气度": 20,
  "趋势强度": 20,
  "回调买点质量": 20,
  "估值与风险收益比": 10,
};

let mobileSnapshot = null;
let mobileSnapshotLoadPromise = null;
let passphrasePromptPromise = null;
const staticSnapshotMode = window.APP_STATIC_SNAPSHOT_MODE === true;

function base64ToBytes(value) {
  const binary = atob(value);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

function requestMobilePassphrase(message = "") {
  if (passphrasePromptPromise) return passphrasePromptPromise;
  passphrasePromptPromise = new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "snapshot-unlock";
    overlay.innerHTML = `
      <form class="snapshot-unlock-panel">
        <span class="snapshot-unlock-mark">A</span>
        <h2>解锁作战台</h2>
        <p>自选股与交易计划已加密，只在本机解锁。</p>
        <label for="snapshotPassphrase">解锁密码</label>
        <input id="snapshotPassphrase" type="password" autocomplete="current-password" required />
        <small>${escapeHtml(message)}</small>
        <button type="submit">解锁</button>
      </form>
    `;
    document.body.appendChild(overlay);
    const form = overlay.querySelector("form");
    const field = overlay.querySelector("input");
    field.focus();
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const value = field.value;
      if (!value) return;
      overlay.remove();
      passphrasePromptPromise = null;
      resolve(value);
    });
  });
  return passphrasePromptPromise;
}

async function decryptMobileSnapshot(envelope) {
  let message = "";
  for (;;) {
    const saved = localStorage.getItem("ashare-mobile-passphrase");
    const passphrase = saved || await requestMobilePassphrase(message);
    try {
      const material = await crypto.subtle.importKey(
        "raw",
        new TextEncoder().encode(passphrase),
        "PBKDF2",
        false,
        ["deriveKey"],
      );
      const key = await crypto.subtle.deriveKey(
        {
          name: "PBKDF2",
          hash: "SHA-256",
          salt: base64ToBytes(envelope.salt),
          iterations: envelope.iterations,
        },
        material,
        { name: "AES-GCM", length: 256 },
        false,
        ["decrypt"],
      );
      const plaintext = await crypto.subtle.decrypt(
        { name: "AES-GCM", iv: base64ToBytes(envelope.iv) },
        key,
        base64ToBytes(envelope.ciphertext),
      );
      localStorage.setItem("ashare-mobile-passphrase", passphrase);
      return JSON.parse(new TextDecoder().decode(plaintext));
    } catch (error) {
      localStorage.removeItem("ashare-mobile-passphrase");
      message = "密码不正确，请重新输入。";
    }
  }
}

async function loadMobileSnapshot(force = false) {
  if (mobileSnapshot && !force) return mobileSnapshot;
  if (mobileSnapshotLoadPromise && !force) return mobileSnapshotLoadPromise;
  mobileSnapshotLoadPromise = (async () => {
    const url = staticSnapshotMode
      ? "../data/mobile_snapshot.enc.json"
      : "/data/mobile_snapshot.json";
    const requestUrl = force ? `${url}?refresh=${Date.now()}` : url;
    const response = await fetch(requestUrl, { cache: "no-store" });
    if (!response.ok) throw new Error(`快照 ${response.status}`);
    const payload = await response.json();
    mobileSnapshot = staticSnapshotMode && payload.ciphertext
      ? await decryptMobileSnapshot(payload)
      : payload;
    return mobileSnapshot;
  })();
  try {
    return await mobileSnapshotLoadPromise;
  } finally {
    mobileSnapshotLoadPromise = null;
  }
}

async function snapshotFallback(url) {
  const snapshot = await loadMobileSnapshot();
  const parsed = new URL(url, window.location.origin);
  if (parsed.pathname === "/api/watchlist") return snapshot.watchlist;
  if (parsed.pathname === "/api/provider") return snapshot.provider;
  if (parsed.pathname === "/api/daily-brief") return snapshot.dailyBrief;
  if (parsed.pathname === "/api/industry-insight") return snapshot.industryInsight;
  if (parsed.pathname === "/api/sector-rankings") return snapshot.sectorRankings;
  if (parsed.pathname === "/api/market-sentiment") return snapshot.marketSentiment;
  if (parsed.pathname === "/api/sector-detail") {
    return snapshot.sectorDetails?.[parsed.searchParams.get("group")];
  }
  if (parsed.pathname === "/api/evaluate") {
    const query = (parsed.searchParams.get("q") || "").trim();
    const direct = snapshot.evaluations?.[query];
    if (direct) return direct;
    return Object.values(snapshot.evaluations || {}).find((item) => {
      const stock = item?.stock || {};
      return stock.name === query || stock.code === query;
    });
  }
  return null;
}

async function fetchJsonWithSnapshot(url) {
  if (staticSnapshotMode) {
    const fallback = await snapshotFallback(url);
    if (fallback) return fallback;
    throw new Error("该股票尚未包含在已发布快照中");
  }
  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`API ${response.status}`);
    return await response.json();
  } catch (error) {
    const fallback = await snapshotFallback(url);
    if (fallback) return fallback;
    throw error;
  }
}

const form = document.querySelector("#searchForm");
const input = document.querySelector("#stockInput");
const canvas = document.querySelector("#priceCanvas");
const ctx = canvas.getContext("2d");
const searchStatus = document.querySelector("#searchStatus");
const chartPeriodLabel = document.querySelector("#chartPeriodLabel");
const periodButtons = [...document.querySelectorAll("[data-period]")];
const chartDateFrom = document.querySelector("#chartDateFrom");
const chartDateTo = document.querySelector("#chartDateTo");
const chartRangeNote = document.querySelector("#chartRangeNote");
const rangePresetButtons = [...document.querySelectorAll("[data-range-months]")];
const refreshSentimentButton = document.querySelector("#refreshSentiment");
const homeRefreshBar = document.querySelector("#homeRefreshBar");
const refreshHomeButton = document.querySelector("#refreshHome");
const homeRefreshStatus = document.querySelector("#homeRefreshStatus");
const homePriceFreshness = document.querySelector("#homePriceFreshness");
const homeAnalysisFreshness = document.querySelector("#homeAnalysisFreshness");
const homeLevelBasis = document.querySelector("#homeLevelBasis");
const dailyBriefView = document.querySelector("#dailyBriefView");
const refreshDailyBriefButton = document.querySelector("#refreshDailyBrief");
const watchlistView = document.querySelector("#watchlistView");
const industryInsightView = document.querySelector("#industryInsightView");
const industryChainRows = document.querySelector("#industryChainRows");
const industryInsightSummary = document.querySelector("#industryInsightSummary");
const refreshIndustryInsightButton = document.querySelector("#refreshIndustryInsight");
const detailView = document.querySelector("#detailView");
const watchlistRows = document.querySelector("#watchlistRows");
const battleGroups = document.querySelector("#battleGroups");
const emptyWatchlist = document.querySelector("#emptyWatchlist");
const watchlistSummary = document.querySelector("#watchlistSummary");
const sectorRankView = document.querySelector("#sectorRankView");
const sectorRankRows = document.querySelector("#sectorRankRows");
const sectorRankSummary = document.querySelector("#sectorRankSummary");
const sectorDetail = document.querySelector("#sectorDetail");
const watchlistToggle = document.querySelector("#watchlistToggle");
const watchlistActionStatus = document.querySelector("#watchlistActionStatus");
const refreshWatchlistFundamentalsButton = document.querySelector("#refreshWatchlistFundamentals");
const refreshFundamentalButton = document.querySelector("#refreshFundamental");
const refreshKlineButton = document.querySelector("#refreshKline");
const backToWatchlist = document.querySelector("#backToWatchlist");
let latestProviderStatus = null;
let latestMarketSentiment = null;
let latestWatchlist = [];
let latestSectorRankings = [];
let latestDailyBrief = null;
let latestIndustryInsight = null;
let currentStock = null;
let activePeriod = "daily";
let chartRange = { from: null, to: null };
let chartRangeStockCode = null;
let chartDrag = null;

function findStock(query) {
  const clean = query.trim().toLowerCase();
  if (!clean) {
    return {
      stock: stocks[0],
      status: "已加载默认样例。输入股票代码或简称后可切换评估。",
    };
  }

  const matched = stocks.find(
    (item) =>
      item.code.toLowerCase() === clean ||
      item.name.toLowerCase().includes(clean) ||
      item.industry.toLowerCase().includes(clean),
  );

  if (matched) {
    return {
      stock: matched,
      status: `已命中内置样例：${matched.code} ${matched.name}。`,
    };
  }

  if (/^\d{6}$/.test(clean)) {
    return {
      stock: createPendingStock(clean),
      status: `已识别 ${clean}，当前未接真实行情/财报接口，先展示待接数据的评分框架。`,
    };
  }

  return {
    stock: createUnknownStock(query.trim()),
    status: `没有找到“${query.trim()}”。建议输入 6 位 A 股代码，或先试 300750、300308、002594、601899。`,
  };
}

function createPendingStock(code) {
  return {
    code,
    name: `待接入股票 ${code}`,
    industry: inferBoard(code),
    hasScore: false,
    setup: "已识别代码，等待真实行情后计算趋势、主线和流动性低点",
    setupType: "待评估",
    price: null,
    trigger: null,
    invalid: null,
    trend: [],
    scores: {
      "基本面与扩产质量": null,
      "行业/主线景气度": null,
      "趋势强度": null,
      "回调买点质量": null,
      "估值与风险收益比": null,
    },
    capacity: {
      stage: "待接财报",
      signals: [
        "真实版本需要读取营收、扣非利润、现金流、在建工程、固定资产和资本开支。",
        "扩产期利润承压不会直接扣死，会结合订单、行业供需和库存周转判断。",
        "未接入财报前，只能展示框架，不给真实建仓或加仓结论。",
      ],
    },
    buySignals: [
      "等待日线、周线、成交量和板块强度数据后识别流动性低点。",
      "真实接口接入后，同一代码会先读本地缓存，缓存失效才进入限速队列。",
      "当前不生成买入分数，避免把数据不足误读为股票强弱。",
    ],
  };
}

function createUnknownStock(label) {
  const fallback = createPendingStock("------");
  return {
    ...fallback,
    code: "未识别",
    name: label || "未输入股票",
    industry: "请输入 6 位代码",
    hasScore: false,
    setup: "输入格式未匹配，无法进入股票评估",
    scores: {
      "基本面与扩产质量": null,
      "行业/主线景气度": null,
      "趋势强度": null,
      "回调买点质量": null,
      "估值与风险收益比": null,
    },
    capacity: {
      stage: "无法评估",
      signals: [
        "当前原型支持内置样例和 6 位 A 股代码。",
        "股票简称需要后续接入本地证券基础表后才能全市场检索。",
        "请输入代码后再做趋势和基本面框架评估。",
      ],
    },
    buySignals: [
      "没有有效代码，无法计算计划低吸区、回收确认价和失效价。",
      "先输入 6 位代码，系统会进入待接真实数据评估态。",
      "接入数据源后，会支持代码、简称、拼音首字母检索。",
    ],
  };
}

function inferBoard(code) {
  if (code.startsWith("688")) return "科创板";
  if (code.startsWith("300") || code.startsWith("301")) return "创业板";
  if (code.startsWith("8") || code.startsWith("4")) return "北交所";
  if (code.startsWith("6")) return "沪市主板";
  if (code.startsWith("0")) return "深市主板";
  return "A股";
}

function buildPendingTrend(price, pullback) {
  const start = price * 0.82;
  const raw = pullback
    ? [0.82, 0.86, 0.9, 0.94, 1.0, 1.08, 1.14, 1.11, 1.05, 1.0, 0.98, 1.0, 1.02]
    : [0.78, 0.8, 0.84, 0.87, 0.9, 0.95, 1.0, 1.04, 1.02, 1.01, 1.03, 1.05, 1.04];
  return raw.map((item) => Number(((start / 0.82) * item).toFixed(2)));
}

function totalScore(stock) {
  if (stock.hasScore === false) return null;
  return Object.values(stock.scores).reduce((sum, item) => sum + item, 0);
}

function strengthPriorityLevel(stock) {
  return stock?.strength?.priority?.level || null;
}

function decision(score, stock) {
  if (score === null) {
    return {
      tone: "no-score",
      title: "数据不足",
      text: "当前没有真实行情、财报和板块数据，暂不生成买入评分。",
    };
  }
  const executionGate = stock?.executionPlan?.executionGate;
  const blockReasons = stock?.executionPlan?.blockReasons || [];
  const blockActions = stock?.executionPlan?.blockActions || [];
  if (executionGate === "禁止买入") {
    const reasonText = blockReasons
      .map((item) => String(item).replace(/[。；]+$/u, ""))
      .join("；");
    const actionText = blockActions
      .map((item) => String(item).replace(/[。；]+$/u, ""))
      .join("；");
    return {
      tone: "risk",
      title: "禁止买入",
      text: blockReasons.length
        ? `原因：${reasonText}。${actionText ? `解除条件：${actionText}。` : ""}`
        : "当前执行闸门关闭，综合分不产生买入动作。",
    };
  }
  if (["等待低吸位", "等待恐慌触发", "等待衰竭", "等待回收", "等待修复"].includes(executionGate)) {
    return {
      tone: "watch",
      title: executionGate,
      text: executionGate === "等待低吸位"
        ? "当前价格高于计划低吸区，不能把趋势强或高分解释为追涨买入。"
        : executionGate === "等待恐慌触发"
          ? "价格已接近低位，但尚未出现恐慌释放，区间中部不提前埋伏。"
          : executionGate === "等待衰竭"
            ? "价格触及低位但抛压尚未衰竭，放量下跌不能直接当成最低点。"
          : executionGate === "等待回收"
            ? "低位出现释放但尚未回收，继续等待价格确认，避免直接接刀。"
            : "当前价格或结构已经失效，先等待止跌并重新站回结构支撑。",
    };
  }
  if (executionGate === "允许轻仓试错") {
    return {
      tone: "good",
      title: "低点已确认",
      text: "低位已经过次日不创新低确认，只按计划轻仓执行，二次回踩不破后再考虑增加仓位。",
    };
  }
  if (executionGate === "允许极小仓低吸") {
    return {
      tone: "watch",
      title: "最低点博弈",
      text: "强主线低位出现抛压衰竭，但确认尚不完整，只允许极小仓验证。",
    };
  }
  if (executionGate === "谨慎试错") {
    return {
      tone: "watch",
      title: "谨慎验证",
      text: "低点结构初步成立，但板块或个股质量不足以放大仓位。",
    };
  }
  const priority = stock?.strength?.priority || {};
  const level = priority.level || "";
  const groupState = stock?.strength?.groupState || {};
  if (score >= 70 && groupState.gate === "禁止加权") {
    return {
      tone: "watch",
      title: "强股观察",
      text: `个股条件较强，但板块趋势为${groupState.trend || "待确认"}、热度为${groupState.heat || "待确认"}，暂不加仓。`,
    };
  }
  if (score >= 70 && ["B-", "C"].includes(level)) {
    return {
      tone: "watch",
      title: level === "C" ? "暂缓入池" : "轻仓试错",
      text: `综合分较高，但RPS入池优先级为${level} ${priority.label || ""}，不按70分加仓处理。`,
    };
  }
  if (score >= 70 && level === "B") {
    return {
      tone: "watch",
      title: "等待确认",
      text: "方向有强度，但个股RPS未确认，适合等个股重新转强后再提高仓位。",
    };
  }
  if (score >= 80) {
    return {
      tone: "good",
      title: "强候选",
      text: "基本面、主线和趋势均较强，但仍需等待低点回收、二次确认与失效位配合。",
    };
  }
  if (score >= 70) {
    return {
      tone: "watch",
      title: "重点跟踪",
      text: "选股质量较好，但是否买入只由流动性低点和执行闸门决定。",
    };
  }
  if (score >= 60) {
    return {
      tone: "watch",
      title: "普通跟踪",
      text: "条件具备部分优势，暂不因评分直接产生建仓动作。",
    };
  }
  return {
    tone: "risk",
    title: "观察为主",
    text: "当前条件不够完整，先等趋势或买点重新确认。",
  };
}

function renderStock(stock) {
  const score = totalScore(stock);
  stock.totalScore = score;
  const action = decision(score, stock);
  document.body.classList.remove("good", "watch", "risk", "no-score");
  document.body.classList.add(action.tone);
  document.body.style.setProperty("--score-deg", `${score ? score * 3.6 : 0}deg`);

  setText("stockCode", `${stock.code} · ${stock.industry}`);
  setText("stockName", stock.name);
  setText("phaseTag", stock.capacity.stage);
  setText("totalScore", score === null ? "--" : score);
  setText("actionTitle", action.title);
  setText("actionText", action.text);
  setText("poolScore", stock.poolScore === null || stock.poolScore === undefined ? "待计算" : stock.poolScore);
  setText("entryScore", stock.entryScore === null || stock.entryScore === undefined ? "待计算" : stock.entryScore);
  setText("invalidPrice", stock.invalid === null || stock.invalid === undefined ? "待计算" : stock.invalid.toFixed(2));
  setText("setupTitle", stock.setup);
  setText("setupType", stock.setupType);
  setText("capacityStage", stock.capacity.stage);
  const priorityLevel = strengthPriorityLevel(stock);
  setText(
    "scoreStatus",
    score === null ? "暂无评分" : priorityLevel ? `${action.title} · ${priorityLevel}` : score >= 70 ? "重点跟踪" : score >= 60 ? "可跟踪" : "先观察",
  );

  currentStock = stock;
  initializeChartRange(stock);
  renderBreakdown(stock);
  renderDecisionSummary(stock, score, action);
  renderDecisionLoop(stock.decisionLoop);
  renderTraderChecklist(stock.traderChecklist);
  renderFundamental(stock.fundamental);
  renderList("buySignals", [
    tradeSummary(stock),
    ...stock.buySignals,
  ]);
  renderExecutionPlan(stock);
  renderSwingExitPlan(stock.swingExitPlan, stock.analysisMeta);
  renderList("capacitySignals", stock.capacity.signals);
  renderQuotePanel(stock);
  renderMetrics(stock);
  renderTimeframes(stock.timeframes);
  renderStrength(stock.strength);
  renderMarketSentiment(stock.marketSentiment || latestMarketSentiment);
  updateWatchlistButton();
  drawChart(stock);
}

function setText(id, value) {
  document.querySelector(`#${id}`).textContent = value;
}

function renderBreakdown(stock) {
  const wrap = document.querySelector("#scoreBreakdown");
  wrap.innerHTML = "";
  Object.entries(weights).forEach(([name, weight]) => {
    const value = stock.scores[name];
    const row = document.createElement("div");
    row.className = "score-row";
    const percent = value === null ? 0 : (value / weight) * 100;
    const displayName = name === "回调买点质量" ? "流动性买点质量" : name;
    row.innerHTML = `
      <span>${displayName}</span>
      <div class="bar"><span style="width: ${percent}%"></span></div>
      <strong>${value === null ? "待接入" : `${value}/${weight}`}</strong>
    `;
    wrap.appendChild(row);
  });
}

function renderDecisionSummary(stock, score, action) {
  const plan = stock.executionPlan || {};
  const strength = stock.strength || {};
  const priority = strength.priority || {};
  const market = stock.marketSentiment?.marketState || {};
  const positionSwitch = market.positionSwitch || {};
  const poolLabel = [priority.level, priority.label].filter(Boolean).join(" ") || (score === null ? "待接入" : "普通观察");
  const entryLabel = plan.executionGate
    ? `${plan.executionGate} / ${plan.trialStatus || "待确认"}`
    : action.title || "待确认";
  const positionLabel = plan.trialPosition
    ? `${plan.trialPosition}${plan.addPosition ? `，加仓：${plan.addPosition}` : ""}`
    : positionSwitch.maxPosition || "待确认";
  const riskLabel = plan.invalidPrice
    ? `失效 ${priceOrPending(plan.invalidPrice)}`
    : stock.invalid ? `失效 ${priceOrPending(stock.invalid)}` : "待计算";

  setText("decisionStatus", action.title || "待计算");
  setText("decisionPool", poolLabel);
  setText("decisionEntry", entryLabel);
  setText("decisionPosition", positionLabel);
  setText("decisionRisk", riskLabel);

  renderList("decisionReasons", [
    action.text,
    priority.reason,
    plan.signals?.[0],
    plan.signals?.[2],
    positionSwitch.reason,
  ].filter(Boolean).slice(0, 5));
}

function renderDecisionLoop(loop) {
  if (!loop) {
    setText("decisionLoopStatus", "待确认");
    setText("decisionMainline", "待接入");
    setText("decisionCycle", "待接入");
    setText("decisionAction", "待接入");
    setText("decisionPassive", "待接入");
    setText("decisionKill", "待接入");
    setText("decisionFundamental", "待接入");
    return;
  }
  setText("decisionLoopStatus", loop.action || "待确认");
  setText("decisionMainline", loop.mainline || "待接入");
  setText("decisionCycle", loop.cycle || "待接入");
  setText("decisionAction", loop.action || "待接入");
  setText("decisionPassive", loop.passive || "待接入");
  setText("decisionKill", loop.risk || "待接入");
  setText("decisionFundamental", loop.fundamental || "待接入");
}

function checklistStatusLabel(status) {
  if (status === "pass") return "通过";
  if (status === "fail") return "否决";
  return "待确认";
}

function renderTraderChecklist(checklist) {
  const wrap = document.querySelector("#traderChecklist");
  if (!wrap) return;
  wrap.innerHTML = "";
  if (!checklist?.items?.length) {
    setText("traderChecklistStatus", "待确认");
    wrap.innerHTML = `<div class="empty-watchlist"><strong>检查清单待接入</strong><span>完成行情、板块和基本面读取后自动生成。</span></div>`;
    return;
  }
  setText(
    "traderChecklistStatus",
    `${checklist.verdict || "待确认"} · 通过${checklist.passCount || 0}/否决${checklist.failCount || 0}`,
  );
  checklist.items.forEach((item) => {
    const row = document.createElement("div");
    row.className = `checklist-item ${item.status || "warn"}`;
    row.innerHTML = `
      <span>${escapeHtml(checklistStatusLabel(item.status))}</span>
      <div>
        <strong>${escapeHtml(item.label || "检查项")}</strong>
        <small>${escapeHtml(item.evidence || "依据待确认")}</small>
        <em>${escapeHtml(item.action || "")}</em>
      </div>
    `;
    wrap.appendChild(row);
  });
  const action = document.createElement("div");
  action.className = "checklist-action";
  action.textContent = checklist.action || "等待确认。";
  wrap.appendChild(action);
}

function renderList(id, items) {
  const list = document.querySelector(`#${id}`);
  list.innerHTML = "";
  items.forEach((text) => {
    const li = document.createElement("li");
    li.textContent = text;
    list.appendChild(li);
  });
}

function showWatchlistView() {
  homeRefreshBar?.classList.remove("hidden");
  dailyBriefView?.classList.remove("hidden");
  watchlistView?.classList.remove("hidden");
  industryInsightView?.classList.remove("hidden");
  sectorRankView?.classList.remove("hidden");
  detailView?.classList.add("hidden");
  document.body.classList.remove("good", "watch", "risk", "no-score");
  searchStatus.textContent = "打开 App 默认展示选股池；搜索任意股票可进入评分详情。";
  const url = new URL(window.location.href);
  url.searchParams.delete("stock");
  window.history.replaceState({}, "", url);
}

function showDetailView() {
  homeRefreshBar?.classList.add("hidden");
  dailyBriefView?.classList.add("hidden");
  watchlistView?.classList.add("hidden");
  industryInsightView?.classList.add("hidden");
  sectorRankView?.classList.add("hidden");
  detailView?.classList.remove("hidden");
}

function isCurrentStockInWatchlist() {
  return Boolean(currentStock?.code && latestWatchlist.some((item) => item.code === currentStock.code));
}

function updateWatchlistButton() {
  if (!watchlistToggle) return;
  const valid = currentStock?.code && !["未识别", "------"].includes(currentStock.code);
  watchlistToggle.disabled = !valid;
  watchlistToggle.textContent = isCurrentStockInWatchlist() ? "移出选股池" : "加入选股池";
  if (refreshFundamentalButton) {
    refreshFundamentalButton.disabled = !valid;
  }
  if (refreshKlineButton) {
    refreshKlineButton.disabled = !valid;
  }
  if (watchlistActionStatus) {
    if (!valid) {
      watchlistActionStatus.textContent = "当前股票无法加入";
    } else if (watchlistActionStatus.textContent === "当前股票无法加入") {
      watchlistActionStatus.textContent = "";
    }
  }
}

function watchlistValue(value, fallback = "待接入") {
  return value === null || value === undefined || value === "" ? fallback : value;
}

function watchlistTrialText(item) {
  if (item.trialRange !== null && item.trialRange !== undefined && item.trialRange !== "") {
    return item.trialRange;
  }
  if (item.trialStatus) return item.trialStatus;
  return item.lastScore === null || item.lastScore === undefined ? "待接入" : "计划区未形成";
}

function watchlistInvalidText(item) {
  if (item.invalid !== null && item.invalid !== undefined) {
    return Number(item.invalid).toFixed(2);
  }
  if (item.trialStatus === "无有效支撑") return "暂不生成";
  if (item.trialStatus) return "失效位待确认";
  return item.lastScore === null || item.lastScore === undefined ? "待接入" : "失效位未形成";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderWatchlistTags(tags) {
  const items = Array.isArray(tags) ? tags.filter(Boolean).slice(0, 3) : [];
  if (!items.length) return "";
  return `<span class="watchlist-tags">${items.map((tag) => `<i>${escapeHtml(tag)}</i>`).join("")}</span>`;
}

function renderBattleGroups(groups) {
  if (!battleGroups) return;
  const list = Array.isArray(groups) ? groups : [];
  battleGroups.innerHTML = "";
  list.forEach((group) => {
    const card = document.createElement("div");
    const names = (group.items || []).map((item) => item.name || item.code).join("、") || "暂无";
    card.innerHTML = `
      <small>${escapeHtml(group.key)}</small>
      <strong>${group.count || 0}</strong>
      <span>${escapeHtml(group.label || "")}</span>
      <em>${escapeHtml(names)}</em>
    `;
    battleGroups.appendChild(card);
  });
}

function actionGroupCount(groups, key) {
  return (groups || []).find((item) => item.key === key)?.count || 0;
}

function renderDailyBrief(payload) {
  latestDailyBrief = payload || null;
  if (!payload?.ok) {
    setText("dailyBriefSummary", payload?.reason || "读取失败");
    renderList("briefNotes", ["复盘数据暂不可用。"]);
    return;
  }
  const sectorActions = payload.sectorActions || [];
  const watchActions = payload.watchlistActions || [];
  const focusGroups = payload.focusGroups || [];
  const actionItems = payload.actionItems || [];
  const market = payload.market || {};
  setText("dailyBriefSummary", payload.updatedAt || "已更新");
  setText("briefMarket", `${market.state || "待确认"} · ${market.position || "待确认"}`);
  setText("briefMarketAction", market.action || "等待确认");
  setText(
    "briefSectors",
    `回调优先 ${actionGroupCount(sectorActions, "回调优先")} / 回避 ${actionGroupCount(sectorActions, "回避加仓")}`,
  );
  setText("briefFocusGroups", focusGroups.length ? focusGroups.join("、") : "暂无明确主线");
  setText(
    "briefWatchlist",
    `试错 ${actionGroupCount(watchActions, "可试错")} / 等回踩 ${actionGroupCount(watchActions, "等回踩")} / 降权 ${actionGroupCount(watchActions, "降权处理")}`,
  );
  setText("briefPrimaryAction", (payload.notes || [])[3] || "等待确认");

  const wrap = document.querySelector("#briefActionItems");
  if (wrap) {
    wrap.innerHTML = "";
    actionItems.forEach((item) => {
      const chip = document.createElement("button");
      chip.className = "brief-action-chip";
      chip.type = "button";
      chip.dataset.openStock = item.code || "";
      chip.innerHTML = `
        <small>${escapeHtml(item.bucket || "观察")}</small>
        <strong>${escapeHtml(item.name || item.code || "--")}</strong>
        <span>${escapeHtml(item.note || item.action || "等待确认")}</span>
      `;
      wrap.appendChild(chip);
    });
    if (!actionItems.length) {
      wrap.innerHTML = `<span class="muted-cell">当前没有明确单票动作。</span>`;
    }
  }
  renderList("briefNotes", payload.notes || []);
}

async function loadDailyBrief() {
  if (refreshDailyBriefButton) {
    refreshDailyBriefButton.disabled = true;
    refreshDailyBriefButton.textContent = "刷新中";
  }
  try {
    const payload = await fetchDailyBrief();
    renderDailyBrief(payload);
  } catch (error) {
    renderDailyBrief({ ok: false, reason: error.message || "读取失败" });
  } finally {
    if (refreshDailyBriefButton) {
      refreshDailyBriefButton.disabled = false;
      refreshDailyBriefButton.textContent = "刷新复盘";
    }
  }
}

function renderIndustryInsight(payload) {
  latestIndustryInsight = payload || null;
  if (industryInsightSummary) {
    industryInsightSummary.textContent = payload?.ok ? payload.summary || payload.updatedAt || "已更新" : payload?.reason || "读取失败";
  }
  if (!industryChainRows) return;
  industryChainRows.innerHTML = "";
  const chains = payload?.chains || [];
  if (!payload?.ok || !chains.length) {
    industryChainRows.innerHTML = `<div class="empty-watchlist"><strong>产业链洞察暂不可用</strong><span>${escapeHtml(payload?.reason || "等待板块样本补全后生成。")}</span></div>`;
    return;
  }
  chains.forEach((chain) => {
    const card = document.createElement("article");
    card.className = "industry-chain-card";
    card.innerHTML = `
      <div class="industry-chain-head">
        <div>
          <small>${escapeHtml(chain.action || "观察")}</small>
          <strong>${escapeHtml(chain.key || "产业链")}</strong>
          <span>${escapeHtml(chain.logic || "")}</span>
        </div>
        <b>${sectorValue(chain.score)}</b>
      </div>
      <div class="industry-chain-metrics">
        <div><small>RPS20</small><strong>${sectorValue(chain.rps20)}</strong></div>
        <div><small>RPS50</small><strong>${sectorValue(chain.rps50)}</strong></div>
        <div><small>强板块</small><strong>${chain.hotCount || 0}/${chain.groupCount || 0}</strong></div>
        <div><small>降温</small><strong>${chain.riskCount || 0}</strong></div>
      </div>
      <div class="industry-chain-groups">
        ${(chain.groups || []).map((item) => `
          <button type="button" data-open-sector="${escapeHtml(item.group)}">
            <strong>${escapeHtml(item.group)}</strong>
            <span>${escapeHtml(item.tradeAction || "观察")} · RPS20 ${sectorValue(item.rps20)}</span>
          </button>
        `).join("")}
      </div>
      <div class="industry-chain-leaders">
        ${(chain.leaders || []).slice(0, 6).map((item) => `
          <button type="button" data-open-stock="${escapeHtml(item.code)}">
            ${escapeHtml(item.name || item.code)}
            <span>${sectorValue(item.return20, "%")}</span>
          </button>
        `).join("") || `<span class="muted-cell">核心股待接入</span>`}
      </div>
    `;
    industryChainRows.appendChild(card);
  });
}

async function loadIndustryInsight() {
  if (refreshIndustryInsightButton) {
    refreshIndustryInsightButton.disabled = true;
    refreshIndustryInsightButton.textContent = "刷新中";
  }
  try {
    const payload = await fetchIndustryInsight();
    renderIndustryInsight(payload);
  } catch (error) {
    renderIndustryInsight({ ok: false, reason: error.message || "读取失败" });
  } finally {
    if (refreshIndustryInsightButton) {
      refreshIndustryInsightButton.disabled = false;
      refreshIndustryInsightButton.textContent = "刷新洞察";
    }
  }
}

async function refreshHomeData() {
  if (refreshHomeButton) {
    refreshHomeButton.disabled = true;
    refreshHomeButton.textContent = staticSnapshotMode ? "获取中" : "刷新中";
  }
  if (homeRefreshStatus) {
    homeRefreshStatus.textContent = staticSnapshotMode
      ? "正在获取已发布的最新快照..."
      : "正在逐只刷新自选池；不会请求全市场股票...";
  }
  try {
    if (staticSnapshotMode) {
      const previousUpdatedAt = mobileSnapshot?.updatedAt || mobileSnapshot?.completedAt;
      const snapshot = await loadMobileSnapshot(true);
      renderPublishedSnapshot(snapshot);
      if (homeRefreshStatus) {
        const currentUpdatedAt = snapshot.updatedAt || snapshot.completedAt;
        homeRefreshStatus.textContent = previousUpdatedAt && previousUpdatedAt === currentUpdatedAt
          ? `已是最新版本 · ${currentUpdatedAt || "时间未知"}`
          : `已获取新快照 · ${currentUpdatedAt || "时间未知"}`;
      }
      return;
    }
    const payload = await refreshHomePayload();
    renderWatchlist(payload.watchlist?.items || [], payload.watchlist?.battleGroups || []);
    renderDailyBrief(payload.dailyBrief);
    renderIndustryInsight(payload.industryInsight);
    renderSectorRankings(payload.sectorRankings);
    const quoteResults = payload.watchlist?.refreshResults || [];
    const okCount = quoteResults.filter((item) => item.ok).length;
    if (homeRefreshStatus) {
      homeRefreshStatus.textContent = `自选池 ${okCount}/${quoteResults.length} 已刷新 · 板块按本地快照重算 · ${payload.updatedAt || formatTime(Date.now() / 1000)}`;
    }
  } catch (error) {
    if (homeRefreshStatus) {
      homeRefreshStatus.textContent = error.message || "刷新失败";
    }
  } finally {
    if (refreshHomeButton) {
      refreshHomeButton.disabled = false;
      refreshHomeButton.textContent = staticSnapshotMode ? "获取最新快照" : "刷新自选池";
    }
  }
}

function formatSnapshotTime(value) {
  if (!value) return "时间未知";
  if (typeof value === "number") return formatTime(value);
  const parsed = new Date(String(value).replace(" ", "T"));
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed.toLocaleString("zh-CN", {
    hour12: false,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function renderSnapshotFreshness(snapshot) {
  const status = snapshot?.dataStatus || {};
  if (homePriceFreshness) {
    homePriceFreshness.textContent = formatSnapshotTime(status.quoteAsOf || snapshot?.updatedAt);
  }
  if (homeAnalysisFreshness) {
    homeAnalysisFreshness.textContent = formatSnapshotTime(status.analysisAsOf || snapshot?.completedAt || snapshot?.updatedAt);
  }
  if (homeLevelBasis) {
    homeLevelBasis.textContent = status.levelBasis || (snapshot?.mode === "close" ? "收盘确认" : "盘中暂定");
  }
}

function renderPublishedSnapshot(snapshot) {
  renderWatchlist(snapshot.watchlist?.items || [], snapshot.watchlist?.battleGroups || []);
  renderDailyBrief(snapshot.dailyBrief);
  renderIndustryInsight(snapshot.industryInsight);
  renderSectorRankings(snapshot.sectorRankings);
  renderSnapshotFreshness(snapshot);
}

async function checkLatestSnapshot() {
  if (!staticSnapshotMode || !navigator.onLine || document.visibilityState === "hidden") return;
  const previousUpdatedAt = mobileSnapshot?.updatedAt || mobileSnapshot?.completedAt;
  try {
    const snapshot = await loadMobileSnapshot(true);
    const currentUpdatedAt = snapshot.updatedAt || snapshot.completedAt;
    renderSnapshotFreshness(snapshot);
    if (currentUpdatedAt !== previousUpdatedAt) {
      renderPublishedSnapshot(snapshot);
      if (homeRefreshStatus) homeRefreshStatus.textContent = `后台发现新快照 · ${currentUpdatedAt}`;
    }
  } catch {
    // Offline fallback remains available through the service worker.
  }
}

function renderWatchlist(items, battleGroupPayload = null) {
  latestWatchlist = items || [];
  if (watchlistSummary) {
    watchlistSummary.textContent = `${latestWatchlist.length} 只跟踪`;
  }
  renderBattleGroups(battleGroupPayload);
  if (!watchlistRows) return;
  watchlistRows.innerHTML = "";
  emptyWatchlist?.classList.toggle("hidden", latestWatchlist.length > 0);
  latestWatchlist.forEach((item) => {
    const row = document.createElement("tr");
    const note = watchlistValue(item.aiNote || item.note, "待补充");
    const isNew = Array.isArray(item.tags) && item.tags.includes("新");
    row.innerHTML = `
      <td><button class="link-button" type="button" data-open-stock="${escapeHtml(item.code)}"><strong>${escapeHtml(item.name || item.code)}${isNew ? '<i class="watchlist-new-tag">新</i>' : ""}</strong><span>${escapeHtml(item.code)}</span></button></td>
      <td>${escapeHtml(watchlistValue(item.industry))}</td>
      <td><strong>${watchlistValue(item.lastScore, "--")}</strong></td>
      <td>${escapeHtml(watchlistValue(item.lastAction, "观察"))}</td>
      <td><strong>${escapeHtml(watchlistValue(item.aiAction, "观察"))}</strong>${renderWatchlistTags(item.aiTags)}</td>
      <td class="watchlist-loop"><strong>${escapeHtml(watchlistValue(item.mainline, item.industry))}</strong><span>${escapeHtml(watchlistValue(item.passivePlan || item.cycle, item.aiNote))}</span></td>
      <td>${item.lastPrice === null || item.lastPrice === undefined ? "待接入" : Number(item.lastPrice).toFixed(2)}</td>
      <td>${escapeHtml(watchlistTrialText(item))}</td>
      <td>${escapeHtml(watchlistInvalidText(item))}</td>
      <td class="watchlist-note">${escapeHtml(note)}</td>
      <td>${escapeHtml(watchlistValue(item.aiUpdatedAt || item.lastUpdatedAt || item.addedAt, "未更新"))}</td>
      <td>
        <button class="mini-button" type="button" data-open-stock="${escapeHtml(item.code)}">查看</button>
        <button class="mini-button ghost" type="button" data-remove-stock="${escapeHtml(item.code)}">移出</button>
      </td>
    `;
    watchlistRows.appendChild(row);
  });
  updateWatchlistButton();
}

async function loadWatchlist() {
  try {
    const payload = await fetchWatchlist();
    renderWatchlist(payload.items || [], payload.battleGroups || []);
  } catch (error) {
    if (watchlistSummary) {
      watchlistSummary.textContent = "读取失败";
    }
  }
}

function sectorValue(value, suffix = "") {
  return value === null || value === undefined ? "--" : `${Number(value).toFixed(1)}${suffix}`;
}

function sectorRpsPill(value) {
  const number = value === null || value === undefined ? null : Number(value);
  const level = number >= 90 ? "hot" : number >= 80 ? "strong" : number >= 60 ? "warm" : "weak";
  const width = number === null ? 0 : Math.max(4, Math.min(100, number));
  return `
    <span class="sector-rps-pill ${level}">
      <i style="width:${width}%"></i>
      <b>${number === null ? "--" : number.toFixed(1)}</b>
    </span>
  `;
}

function renderSectorLeaders(leaders) {
  const items = Array.isArray(leaders) ? leaders.slice(0, 4) : [];
  if (!items.length) return "<span class=\"muted-cell\">待接入</span>";
  return items
    .map((item) => `<button class="sector-leader" type="button" data-open-stock="${escapeHtml(item.code)}">${escapeHtml(item.name || item.code)}<span>${sectorValue(item.return20, "%")}</span></button>`)
    .join("");
}

function renderSectorLayerItems(items) {
  const list = Array.isArray(items) ? items : [];
  if (!list.length) return "<span class=\"muted-cell\">暂无</span>";
  return list
    .map((item) => `
      <button class="sector-stock-chip ${item.isWatchlist ? "tracked" : ""}" type="button" data-open-stock="${escapeHtml(item.code)}">
        <strong>${escapeHtml(item.name || item.code)}</strong>
        <span>RPS50 ${sectorValue(item.rps50)} · 20日 ${sectorValue(item.return20, "%")}</span>
      </button>
    `)
    .join("");
}

function jumpToSectorDetail() {
  if (!sectorDetail) return;
  const targetTop = sectorDetail.getBoundingClientRect().top + window.scrollY - 12;
  const url = new URL(window.location.href);
  url.hash = "sectorDetail";
  window.history.replaceState({}, "", url);
  window.scrollTo({ top: Math.max(0, targetTop), behavior: "auto" });
  sectorDetail.focus({ preventScroll: true });
}

function scheduleSectorDetailJump() {
  requestAnimationFrame(() => {
    jumpToSectorDetail();
    window.setTimeout(jumpToSectorDetail, 80);
    window.setTimeout(jumpToSectorDetail, 240);
  });
}

function renderSectorDetail(payload) {
  if (!sectorDetail) return;
  if (!payload?.ok) {
    sectorDetail.classList.remove("hidden");
    sectorDetail.innerHTML = `<div class="empty-watchlist"><strong>板块详情暂不可用</strong><span>${escapeHtml(payload?.reason || "样本不足。")}</span></div>`;
    scheduleSectorDetailJump();
    return;
  }
  const rps = payload.groupRps || {};
  const thesis = payload.thesis || {};
  const state = payload.state || {};
  const risk = payload.risk || {};
  const quality = payload.quality || {};
  const qualityFlags = quality.flags || [];
  sectorDetail.classList.remove("hidden");
  sectorDetail.innerHTML = `
    <div class="sector-detail-head">
      <div>
        <p class="eyebrow">板块详情</p>
        <h3>${escapeHtml(payload.group)}</h3>
        <span>${escapeHtml(thesis.phase || "阶段待确认")} · ${escapeHtml(thesis.action || state.gate || "观察")} · ${escapeHtml(risk.label || "风险待确认")}</span>
      </div>
      <button class="mini-button ghost" type="button" data-close-sector-detail>收起</button>
    </div>
    <div class="sector-detail-grid">
      <div><small>样本</small><strong>${payload.sampleSize || "--"}</strong></div>
      <div><small>质量分</small><strong>${sectorValue(quality.score)}</strong></div>
      <div><small>红线</small><strong>${payload.groupRed80 || 0}/4</strong></div>
      <div><small>扩散</small><strong>${sectorValue(payload.aboveMa20Ratio, "%")}</strong></div>
      <div><small>5日上涨</small><strong>${sectorValue(payload.positive5Ratio, "%")}</strong></div>
      <div><small>量能</small><strong>${payload.amountRatio20 === null || payload.amountRatio20 === undefined ? "--" : `${Number(payload.amountRatio20).toFixed(2)}x`}</strong></div>
    </div>
    <div class="sector-rps-grid detail-rps">
      <label><span>5日</span>${sectorRpsPill(rps.groupRps5)}</label>
      <label><span>10日</span>${sectorRpsPill(rps.groupRps10)}</label>
      <label><span>20日</span>${sectorRpsPill(rps.groupRps20)}</label>
      <label><span>50日</span>${sectorRpsPill(rps.groupRps50)}</label>
    </div>
    <div class="sector-detail-note">
      <strong>${escapeHtml(`${quality.label || "质量待确认"} · ${thesis.reason || state.reason || ""}`)}</strong>
      <span>${escapeHtml((qualityFlags.length ? qualityFlags : risk.signals || []).join("；"))}</span>
    </div>
    ${(payload.watchlistItems || []).length ? `
      <div class="sector-layer tracked-layer">
        <div><strong>我的票</strong><span>${payload.watchlistItems.length} 只</span></div>
        <div class="sector-layer-items">${renderSectorLayerItems(payload.watchlistItems)}</div>
      </div>
    ` : ""}
    <div class="sector-layers">
      ${(payload.layers || []).map((layer) => `
        <div class="sector-layer">
          <div><strong>${escapeHtml(layer.key)}</strong><span>${layer.count || 0} 只</span></div>
          <div class="sector-layer-items">${renderSectorLayerItems(layer.items)}</div>
        </div>
      `).join("")}
    </div>
  `;
  scheduleSectorDetailJump();
}

async function loadSectorDetail(group) {
  if (!sectorDetail) return;
  sectorDetail.classList.remove("hidden");
  sectorDetail.innerHTML = `<div class="empty-watchlist"><strong>正在读取板块详情</strong><span>${escapeHtml(group)}</span></div>`;
  scheduleSectorDetailJump();
  try {
    const payload = await fetchSectorDetail(group);
    renderSectorDetail(payload);
  } catch (error) {
    renderSectorDetail({ ok: false, reason: error.message || "读取失败。" });
  }
}

function renderSectorRankings(payload) {
  const items = payload?.items || [];
  latestSectorRankings = items;
  if (sectorRankSummary) {
    sectorRankSummary.textContent = payload?.ok
      ? `${items.length} 个板块 · 样本 ${payload.sampleSize || "--"}`
      : payload?.reason || "读取失败";
  }
  if (!sectorRankRows) return;
  sectorRankRows.innerHTML = "";
  if (!items.length) {
    sectorRankRows.innerHTML = `<div class="empty-watchlist"><strong>暂未形成排行</strong><span>${escapeHtml(payload?.reason || "等待本地行情样本补全后生成。")}</span></div>`;
    return;
  }

  if (Array.isArray(payload?.actionGroups)) {
    const summary = document.createElement("div");
    summary.className = "sector-action-groups";
    summary.innerHTML = payload.actionGroups
      .map((group) => `
        <div>
          <small>${escapeHtml(group.key)}</small>
          <strong>${group.count || 0}</strong>
          <span>${escapeHtml((group.groups || []).join("、") || "暂无")}</span>
        </div>
      `)
      .join("");
    sectorRankRows.appendChild(summary);
  }

  items.forEach((item, index) => {
    const row = document.createElement("article");
    row.className = "sector-rank-card";
    const rps = item.groupRps || {};
    const thesis = item.thesis || {};
    const state = item.state || {};
    const quality = item.quality || {};
    const qualityFlags = quality.flags || [];
    row.innerHTML = `
      <div class="sector-rank-main">
        <span class="sector-rank-index">${index + 1}</span>
        <div>
          <button class="sector-title-button" type="button" data-open-sector="${escapeHtml(item.group)}">${escapeHtml(item.group)}</button>
          <p>${escapeHtml(item.stageLabel || thesis.phase || "阶段待确认")} · ${escapeHtml(item.tradeAction || thesis.action || state.gate || "观察")} · ${escapeHtml(item.risk?.label || "风险待确认")}</p>
        </div>
        <strong>${sectorValue(item.score)}</strong>
      </div>
      <div class="sector-rps-grid">
        <label><span>5日</span>${sectorRpsPill(rps.groupRps5)}</label>
        <label><span>10日</span>${sectorRpsPill(rps.groupRps10)}</label>
        <label><span>20日</span>${sectorRpsPill(rps.groupRps20)}</label>
        <label><span>50日</span>${sectorRpsPill(rps.groupRps50)}</label>
      </div>
      <div class="sector-metrics">
        <span>质量 <strong>${sectorValue(quality.score)}</strong></span>
        <span>红线 <strong>${item.groupRed80 || 0}/4</strong></span>
        <span>扩散 <strong>${sectorValue(item.aboveMa20Ratio, "%")}</strong></span>
        <span>5日上涨 <strong>${sectorValue(item.positive5Ratio, "%")}</strong></span>
        <span>量能 <strong>${item.amountRatio20 === null || item.amountRatio20 === undefined ? "--" : `${Number(item.amountRatio20).toFixed(2)}x`}</strong></span>
        <span>判断 <strong>${escapeHtml(quality.label || "待确认")}</strong></span>
      </div>
      <div class="sector-quality ${escapeHtml(quality.level || "watch")}">
        <strong>${escapeHtml(quality.label || "质量待确认")}</strong>
        <span>${escapeHtml(qualityFlags.length ? qualityFlags.join("；") : "RPS、扩散和量能暂未出现明显背离。")}</span>
      </div>
      <div class="sector-leaders">${renderSectorLeaders(item.leaders)}<button class="sector-leader detail-link" type="button" data-open-sector="${escapeHtml(item.group)}">详情</button></div>
    `;
    sectorRankRows.appendChild(row);
  });
}

async function loadSectorRankings() {
  try {
    const payload = await fetchSectorRankings();
    renderSectorRankings(payload);
  } catch (error) {
    if (sectorRankSummary) {
      sectorRankSummary.textContent = "读取失败";
    }
    if (sectorRankRows) {
      sectorRankRows.innerHTML = `<div class="empty-watchlist"><strong>板块排行暂不可用</strong><span>本地服务恢复后会自动显示。</span></div>`;
    }
  }
}

function renderQuotePanel(stock) {
  const quote = stock.quote || null;
  setText("quotePrice", quote?.price === null || quote?.price === undefined ? "待接入" : quote.price.toFixed(2));
  setText("quotePct", quote?.pctChange === null || quote?.pctChange === undefined ? "待接入" : `${quote.pctChange}%`);
  setText("quoteTurnover", quote?.turnoverRate === null || quote?.turnoverRate === undefined ? "待接入" : `${quote.turnoverRate}%`);
  setText("quoteSource", quote?.source ? `${quote.source}` : "未启用");

  const provider = latestProviderStatus?.provider || latestProviderStatus?.ths;
  if (!provider) {
    setText("providerMode", "读取中");
    renderList("providerSignals", ["正在读取后端数据源状态。"]);
    return;
  }

  setText("providerMode", provider.enabled ? "同花顺低频开启" : "安全模式");
  const signals = [
    provider.enabled
      ? "同花顺日K只在单股搜索或手动刷新自选池时触发；F10仅由当前股票基本面按钮触发。"
      : "同花顺日K provider 当前关闭，不会请求外部接口。",
    `日K缓存 ${Math.round(provider.klineCacheTtlSeconds / 60)} 分钟，财报缓存 ${Math.round((provider.fundamentalCacheTtlSeconds || 0) / 86400)} 天，题材缓存 ${Math.round((provider.themeCacheTtlSeconds || 0) / 3600)} 小时。`,
    `评分主缓存 ${Math.round(provider.mainCacheTtlSeconds / 60)} 分钟。`,
    `全局外部请求冷却 ${provider.minExternalIntervalSeconds} 秒，失败熔断 ${Math.round(provider.cooldownSeconds / 60)} 分钟。`,
  ];

  if (provider.nextAllowedRemainingSeconds > 0) {
    signals.push(`距离下一次允许外部请求约 ${provider.nextAllowedRemainingSeconds} 秒。`);
  }
  if (provider.blockedRemainingSeconds > 0) {
    signals.push(`当前处于熔断冷却期，剩余约 ${provider.blockedRemainingSeconds} 秒。`);
  }
  if (quote?.quoteTime) {
    signals.push(
      quote.isIntraday
        ? `当前价格为${formatKlineDate(quote.quoteTime)} ${quote.quoteClock || "盘中"}行情；技术评分仍基于${formatKlineDate(quote.scoreDate)}完整日K。`
        : `当前价格对应日K日期：${formatKlineDate(quote.quoteTime)}。`,
    );
  }
  if (quote?.fetchedAt) {
    signals.push(`评分生成时间：${formatTime(quote.fetchedAt)}。`);
  }
  if (stock.analysisMeta?.computedAt) {
    signals.push(`建议计算时间：${formatSnapshotTime(stock.analysisMeta.computedAt)}；${stock.analysisMeta.levelBasis || "按最新结构计算"}。`);
  }
  renderList("providerSignals", signals);
}

function renderMetrics(stock) {
  const inferred = inferMetricsFromText(stock);
  const metrics = { ...inferred, ...(stock.metrics || {}) };
  const plan = stock.executionPlan || {};
  const confirmationExpired = Boolean(
    plan.confirmationExpired
    || (
      plan.addConfirmPrice !== null
      && plan.addConfirmPrice !== undefined
      && stock.price !== null
      && stock.price !== undefined
      && stock.price > plan.addConfirmPrice
    )
  );
  setText("metricsStatus", stock.hasScore ? "已计算" : "待接入");
  setText("metricMa20", valueOrPending(metrics.ma20));
  setText("metricMa60", valueOrPending(metrics.ma60));
  setText("metricNearMa20", percentOrPending(metrics.nearMa20Pct));
  setText("metricDrawdown", percentOrPending(metrics.drawdownPct));
  setText("metricRisk", percentOrPending(metrics.riskPct));
  const confirmationPending = plan.addConfirmPrice === null || plan.addConfirmPrice === undefined;
  setText(
    "metricTriggerDistance",
    confirmationExpired
      ? "已过期"
      : confirmationPending ? "待形成" : percentOrPending(metrics.triggerDistancePct),
  );
  setText("metricVolumeRatio", ratioOrPending(metrics.volumeRatio5To20));
  setText("metricTodayVolumeRatio", ratioOrPending(metrics.todayVolumeRatio20));
  setText("metricAmount", amountOrPending(metrics.amount));
  setText("metricTurnover", percentOrPending(metrics.turnoverRate));
}

function renderFundamental(fundamental) {
  if (!fundamental?.available) {
    setText("fundamentalStage", fundamental?.stage || "待接财报");
    setText("fundamentalScore", fundamental?.score === undefined ? "待接入" : `${fundamental.score}/30`);
    setText("fundamentalQuality", "待夯实");
    setText("fundamentalGrowth", "待接入");
    setText("fundamentalProfit", "待接入");
    setText("fundamentalCashDebt", "待接入");
    setText("fundamentalNext", "刷新当前股票基本面");
    renderList("fundamentalSignals", fundamental?.signals || ["财报缓存未命中，暂不展示基本面分解。"]);
    return;
  }

  const byLabel = Object.fromEntries((fundamental.breakdown || []).map(item => [item.label, item]));
  const quality = fundamental.quality || {};
  setText("fundamentalStage", fundamental.stage || "已接入");
  setText("fundamentalScore", `${fundamental.score}/30`);
  setText("fundamentalQuality", quality.level || "待验证");
  setText("fundamentalGrowth", scorePart(byLabel["增长"], 11));
  setText("fundamentalProfit", scorePart(byLabel["盈利质量"], 13));
  setText("fundamentalCashDebt", scorePart(byLabel["现金流/负债"], 6));
  setText("fundamentalNext", quality.action || "继续补证");
  renderList("fundamentalSignals", [
    ...(fundamental.signals || []).slice(0, 3),
    ...(quality.evidence || []).slice(0, 2),
    ...(quality.risks || []).slice(0, 2),
    ...(quality.gaps || []).slice(0, 2),
  ]);
}

function scorePart(item, maxScore) {
  return item ? `${item.score}/${maxScore}` : "待接入";
}

function renderExecutionPlan(stock) {
  const plan = stock.executionPlan || null;
  if (!plan) {
    setText("executionStatus", "待计算");
    setText("supportBasis", "待接入");
    setText("trialRange", "待接入");
    setText("liquidityStage", "待接入");
    setText("panicTriggerPrice", "待接入");
    setText("reclaimConfirmPrice", "待接入");
    setText("trialPosition", "待接入");
    setText("secondarySupport", "待接入");
    setText("repairConfirmPrice", "待接入");
    setText("addConfirmPrice", "待接入");
    setText("addPosition", "待接入");
    setText("executionInvalid", "待接入");
    setText("trialDistance", "待接入");
    renderList("executionSignals", ["真实日K和买点结构不足，暂不生成执行计划。"]);
    return;
  }

  setText("executionStatus", plan.executionGate || plan.trialStatus || "已计算");
  setText(
    "supportBasis",
    plan.supportPrice
      ? `${plan.supportLabel || "结构支撑"} ${priceOrPending(plan.supportPrice)}${plan.supportAtr ? ` · ATR ${priceOrPending(plan.supportAtr)}` : ""}`
      : plan.supportLabel || "待确认",
  );
  setText(
    "trialRange",
    plan.trialLow !== null
      && plan.trialLow !== undefined
      && plan.trialHigh !== null
      && plan.trialHigh !== undefined
      ? `${priceOrPending(plan.trialLow)}-${priceOrPending(plan.trialHigh)}`
      : "待形成",
  );
  setText("liquidityStage", plan.liquidityStage || plan.trialStatus || "待确认");
  setText(
    "panicTriggerPrice",
    plan.panicTriggerPrice === null || plan.panicTriggerPrice === undefined
      ? "待形成"
      : priceOrPending(plan.panicTriggerPrice),
  );
  setText(
    "reclaimConfirmPrice",
    plan.reclaimConfirmPrice === null || plan.reclaimConfirmPrice === undefined
      ? "待形成"
      : priceOrPending(plan.reclaimConfirmPrice),
  );
  setText("trialPosition", plan.trialPosition || "待确认");
  setText(
    "secondarySupport",
    plan.secondarySupportPrice
      ? `${plan.secondarySupportLabel || "结构支撑"} ${priceOrPending(plan.secondarySupportPrice)}`
      : "暂无可靠防线",
  );
  setText(
    "repairConfirmPrice",
    plan.repairConfirmPrice ? priceOrPending(plan.repairConfirmPrice) : plan.repairState || "趋势已修复",
  );
  const secondConfirmExpired = (
    plan.addConfirmPrice !== null
    && plan.addConfirmPrice !== undefined
    && stock.price !== null
    && stock.price !== undefined
    && stock.price > plan.addConfirmPrice
  );
  setText(
    "addConfirmPrice",
    plan.addConfirmPrice
      ? `${priceOrPending(plan.addConfirmPrice)}${secondConfirmExpired ? " · 已过期" : ""}`
      : "待形成",
  );
  setText("addPosition", plan.addPosition || "待确认");
  setText(
    "executionInvalid",
    plan.invalidPrice === null || plan.invalidPrice === undefined
      ? "待形成"
      : priceOrPending(plan.invalidPrice),
  );
  setText(
    "trialDistance",
    plan.trialDistancePct === null || plan.trialDistancePct === undefined
      ? "待形成"
      : percentOrPending(plan.trialDistancePct),
  );
  renderList("executionSignals", plan.signals || []);
}

function renderSwingExitPlan(plan, analysisMeta = null) {
  const levelsWrap = document.querySelector("#swingExitLevels");
  if (!plan) {
    setText("swingExitStatus", "待计算");
    setText("swingExitCycle", "待接入");
    setText("swingExitSector", "待接入");
    setText("swingExitAcceptance", "待接入");
    setText("swingExitProtection", "待接入");
    setText("swingExitAction", "待接入");
    if (levelsWrap) {
      levelsWrap.innerHTML = '<div class="swing-exit-empty">真实日周月K线不足，暂不生成压力计划。</div>';
    }
    renderList("swingExitSignals", ["等待完整K线、板块强度和波动率数据后计算。"]) ;
    return;
  }

  const protection = plan.protection;
  const basis = analysisMeta?.levelBasis;
  setText(
    "swingExitStatus",
    `${plan.state || (plan.available ? "已计算" : "待形成")}${basis ? ` · ${basis}` : ""}`,
  );
  setText("swingExitCycle", plan.timeframeResonance || "待确认");
  setText("swingExitSector", plan.sectorResonance || "待确认");
  setText("swingExitAcceptance", plan.acceptance?.state || "待确认");
  setText(
    "swingExitProtection",
    protection ? `${priceOrPending(protection.low)}-${priceOrPending(protection.high)}` : "待形成",
  );
  setText("swingExitAction", plan.action || "等待价格接近压力区");

  const levels = plan.levels || [];
  if (levelsWrap) {
    levelsWrap.innerHTML = levels.length
      ? levels.map((level) => `
        <div class="swing-exit-level">
          <div class="swing-exit-level-head">
            <span>${escapeHtml(level.name || "压力区")}</span>
            <i>${escapeHtml(level.grade || "C")}级</i>
          </div>
          <strong>${priceOrPending(level.low)}-${priceOrPending(level.high)}</strong>
          <em>${escapeHtml(level.interaction || "未触及")} · 距现价 ${percentOrPending(level.distancePct)}</em>
          <p>${escapeHtml(level.suggestion || "到压观察承接")}</p>
          <small>${escapeHtml((level.sources || []).join(" · ") || "结构压力")}</small>
        </div>
      `).join("")
      : '<div class="swing-exit-empty">价格处于新高区，使用动态保护位跟踪。</div>';
  }
  renderList("swingExitSignals", plan.signals || []);
}

function timeframeMetricText(frame) {
  if (!frame?.available) {
    return `样本 ${frame?.bars || 0} 根`;
  }
  const fast = valueOrPending(frame.maFast);
  const slow = valueOrPending(frame.maSlow);
  const near = percentOrPending(frame.nearFastPct);
  const drawdown = percentOrPending(frame.drawdownPct);
  return `快线 ${fast} / 慢线 ${slow} / 距快线 ${near} / 回撤 ${drawdown}`;
}

function renderTimeframeCard(prefix, frame) {
  setText(`${prefix}Phase`, frame?.phase || "待接入");
  setText(`${prefix}Action`, frame?.action || "待确认");
  setText(`${prefix}Metrics`, timeframeMetricText(frame));
}

function renderTimeframes(timeframes) {
  if (!timeframes) {
    setText("timeframePosture", "待计算");
    setText("timeframeVerdict", "等待日线、周线、月线数据");
    renderTimeframeCard("monthly", null);
    renderTimeframeCard("weekly", null);
    renderTimeframeCard("daily", null);
    renderList("timeframeSignals", ["真实K线不足，暂未生成三周期定位。"]);
    return;
  }

  setText("timeframePosture", timeframes.posture || "待确认");
  setText("timeframeVerdict", timeframes.verdict || "待确认");
  renderTimeframeCard("monthly", timeframes.monthly);
  renderTimeframeCard("weekly", timeframes.weekly);
  renderTimeframeCard("daily", timeframes.daily);
  renderList("timeframeSignals", timeframes.signals || []);
}

function setSectorRpsBar(idPrefix, value) {
  const safeValue = Number.isFinite(Number(value)) ? Math.max(0, Math.min(100, Number(value))) : null;
  const bar = document.querySelector(`#${idPrefix}Bar`);
  const label = document.querySelector(`#${idPrefix}Value`);
  if (bar) {
    bar.style.width = safeValue === null ? "0%" : `${safeValue}%`;
    bar.className = safeValue >= 90 ? "hot" : safeValue >= 80 ? "strong" : safeValue >= 60 ? "warm" : "weak";
  }
  if (label) {
    label.textContent = safeValue === null ? "--" : safeValue.toFixed(1);
  }
}

function renderSectorTrend(strength) {
  const groupRps = strength?.groupRps || {};
  const values = [
    groupRps.groupRps5,
    groupRps.groupRps10,
    groupRps.groupRps20,
    groupRps.groupRps50,
  ].filter((value) => Number.isFinite(Number(value)));
  setSectorRpsBar("sectorRps5", groupRps.groupRps5);
  setSectorRpsBar("sectorRps10", groupRps.groupRps10);
  setSectorRpsBar("sectorRps20", groupRps.groupRps20);
  setSectorRpsBar("sectorRps50", groupRps.groupRps50);

  if (!values.length) {
    setText("sectorTrendSummary", "待接入");
    return;
  }
  const red80 = values.filter((value) => Number(value) >= 80).length;
  const latest = Number(groupRps.groupRps5);
  const mid = Number(groupRps.groupRps20);
  const direction = Number.isFinite(latest) && Number.isFinite(mid)
    ? latest >= mid + 8
      ? "短线增强"
      : latest <= mid - 8
        ? "短线降温"
        : "强度平稳"
    : "强度待确认";
  setText("sectorTrendSummary", `${red80}/4 红线 · ${direction}`);
}

function renderStrength(strength) {
  if (!strength?.available) {
    setText("strengthStatus", "待计算");
    setText("strengthGroup", "待接入");
    setText("strengthStockRps", "待接入");
    setText("strengthGroupRps", "待接入");
    setText("strengthTrend", "待接入");
    setText("strengthHeat", "待接入");
    setText("sectorPhase", "待接入");
    setText("sectorBreadth", "待接入");
    setText("sectorAction", "待接入");
    setText("stageTopRisk", "待接入");
    setText("strengthRedLines", "待接入");
    setText("strengthAmount", "待接入");
    setText("strengthPriority", "待接入");
    setText("strengthSample", "待接入");
    renderSectorTrend(null);
    renderList("strengthSignals", strength?.signals || [
      "本地RPS样本不足或该股票尚未生成日K评分，暂不展示主线强度。",
    ]);
    return;
  }

  const stockRps = strength.stockRps || {};
  const groupRps = strength.groupRps || {};
  setText("strengthStatus", strength.verdict || "已计算");
  setText("strengthGroup", strength.group || "未匹配");
  setText("strengthStockRps", valueOrPending(stockRps.rps50));
  setText("strengthGroupRps", valueOrPending(groupRps.groupRps20));
  setText("strengthTrend", strength.groupState?.trend || "待确认");
  setText("strengthHeat", strength.groupState?.heat || "待确认");
  setText("sectorPhase", strength.sectorThesis?.phase || "待确认");
  setText("sectorBreadth", strength.sectorThesis?.breadth || "待确认");
  setText("sectorAction", strength.sectorThesis?.action || "待确认");
  const topRisk = strength.stageTopRisk || {};
  const topRiskLabel = topRisk.label
    ? `${topRisk.label}${topRisk.count === undefined ? "" : ` ${topRisk.count}/4`}`
    : "待确认";
  setText("stageTopRisk", topRiskLabel);
  setText("strengthRedLines", `${strength.groupRed80 || 0}/4`);
  setText("strengthAmount", ratioOrPending(groupRps.groupAmountRatio20));
  const priority = strength.priority || {};
  setText("strengthPriority", [priority.level, priority.label].filter(Boolean).join(" ") || "待确认");
  const universeSize = strength.sampleUniverseSize || strength.sampleSize || 0;
  setText("strengthSample", `${strength.groupSize || 0}/${strength.sampleSize || 0}/${universeSize}`);
  renderSectorTrend(strength);
  renderList("strengthSignals", [
    priority.reason,
    ...(strength.signals || []),
  ].filter(Boolean));
}

function renderMarketSentiment(sentiment) {
  const state = sentiment?.marketState || null;
  const positionSwitch = state?.positionSwitch || null;
  if (!sentiment?.ok || !state) {
    setText("marketState", sentiment?.refreshing ? "刷新中" : "待刷新");
    setText("marketUpRatio", "待接入");
    setText("marketPosition", "待接入");
    setText("marketAction", "待接入");
    setText("marketBreadth", "待接入");
    setText("marketLimits", "待接入");
    renderList("marketSignals", [
      sentiment?.reason || "点击刷新后，后端会低频读取同花顺全A聚合接口并写入本地缓存。",
      "市场仓位开关不会在搜索单票时自动刷新，避免额外接口压力。",
    ]);
    if (refreshSentimentButton) {
      refreshSentimentButton.disabled = Boolean(sentiment?.refreshing);
      refreshSentimentButton.textContent = sentiment?.refreshing ? "刷新中" : "刷新";
    }
    return;
  }

  setText("marketState", sentiment.stale ? `${state.state} · 旧缓存` : state.state);
  setText("marketUpRatio", `${state.upRatio}%`);
  setText("marketPosition", positionSwitch?.maxPosition || "待接入");
  setText("marketAction", positionSwitch?.level || "待确认");
  setText("marketBreadth", `${sentiment.upCount}/${sentiment.flatCount}/${sentiment.downCount}`);
  setText("marketLimits", `${sentiment.limitUpCount}/${sentiment.limitDownCount}`);
  const signals = [
    positionSwitch?.action,
    positionSwitch?.reason,
    state.advice,
    `覆盖 ${sentiment.totalCount} 只；缓存年龄 ${Math.round((sentiment.cacheAgeSeconds || 0) / 60)} 分钟。`,
    ...(sentiment.notes || []),
  ].filter(Boolean);
  if (sentiment.refreshing) {
    signals.unshift("后台正在低频刷新，完成后会自动更新本地缓存。");
  }
  renderList("marketSignals", signals);
  if (refreshSentimentButton) {
    refreshSentimentButton.disabled = Boolean(sentiment.refreshing);
    refreshSentimentButton.textContent = sentiment.refreshing ? "刷新中" : "刷新";
  }
}

function inferMetricsFromText(stock) {
  const allText = [
    ...(stock.capacity?.signals || []),
    ...(stock.buySignals || []),
  ].join(" ");
  return {
    ma20: matchNumber(allText, /MA20\s*([0-9.]+)/),
    ma60: matchNumber(allText, /MA60\s*([0-9.]+)/),
    drawdownPct: matchNumber(allText, /60日(?:高点)?回撤\s*([0-9.]+)%/),
    riskPct: matchNumber(allText, /风险距离约\s*([0-9.]+)%/),
    triggerDistancePct: matchNumber(allText, /距(?:触发价|确认价|加仓确认价)约\s*([0-9.]+)%/),
  };
}

function matchNumber(text, pattern) {
  const match = text.match(pattern);
  return match ? Number(match[1]) : null;
}

function valueOrPending(value) {
  return value === null || value === undefined ? "待接入" : value;
}

function priceOrPending(value) {
  return value === null || value === undefined ? "待接入" : Number(value).toFixed(2);
}

function percentOrPending(value) {
  return value === null || value === undefined ? "待接入" : `${value}%`;
}

function ratioOrPending(value) {
  return value === null || value === undefined ? "待接入" : `${value}x`;
}

function amountOrPending(value) {
  if (value === null || value === undefined) {
    return "待接入";
  }
  if (Math.abs(value) >= 100000000) {
    return `${(value / 100000000).toFixed(2)}亿`;
  }
  if (Math.abs(value) >= 10000) {
    return `${(value / 10000).toFixed(0)}万`;
  }
  return `${value}`;
}

function formatTime(seconds) {
  return new Date(seconds * 1000).toLocaleString("zh-CN", {
    hour12: false,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatKlineDate(value) {
  const text = String(value || "");
  const match = text.match(/^(\d{4})-?(\d{2})-?(\d{2})$/);
  return match ? `${match[1]}-${match[2]}-${match[3]}` : text;
}

function drawChart(stock) {
  const width = canvas.width;
  const height = canvas.height;
  const pad = 42;
  const period = periodConfig(activePeriod);
  const rows = chartSeries(stock, activePeriod);
  const data = rows.map((row) => row.close);
  if (chartPeriodLabel) {
    chartPeriodLabel.textContent = `${period.label}结构`;
  }

  if (!data.length) {
    drawEmptyChart(stock);
    return;
  }

  const rawMin = Math.min(...data);
  const rawMax = Math.max(...data);
  const spread = Math.max(rawMax - rawMin, Math.abs(rawMax) * 0.02, 0.01);
  const min = rawMin - spread * 0.2;
  const max = rawMax + spread * 0.2;
  const divisor = Math.max(1, data.length - 1);
  const points = data.map((value, index) => ({
    x: pad + (index / divisor) * (width - pad * 2),
    y: height - pad - ((value - min) / (max - min)) * (height - pad * 2),
  }));

  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#fbfcfb";
  ctx.fillRect(0, 0, width, height);

  ctx.strokeStyle = "#e5ebe7";
  ctx.lineWidth = 1;
  for (let i = 0; i < 5; i += 1) {
    const y = pad + i * ((height - pad * 2) / 4);
    ctx.beginPath();
    ctx.moveTo(pad, y);
    ctx.lineTo(width - pad, y);
    ctx.stroke();
  }

  const zoneStart = points[Math.max(0, points.length - 5)].x;
  const zoneEnd = points[points.length - 1].x;
  ctx.fillStyle = "rgba(255, 245, 220, 0.92)";
  ctx.fillRect(zoneStart, pad, zoneEnd - zoneStart, height - pad * 2);

  const ma = movingAverage(data, 4);
  drawLine(
    ma.map((value, index) => ({
      x: points[index].x,
      y: height - pad - ((value - min) / (max - min)) * (height - pad * 2),
    })),
    "#2f5f9f",
    3,
  );
  drawLine(points, "#117a65", 4);

  points.forEach((point, index) => {
    ctx.beginPath();
    ctx.fillStyle = index === points.length - 1 ? "#b94035" : "#117a65";
    ctx.arc(point.x, point.y, index === points.length - 1 ? 6 : 4, 0, Math.PI * 2);
    ctx.fill();
  });

  ctx.fillStyle = "#64716c";
  ctx.font = "22px system-ui";
  ctx.fillText(`${stock.name} ${period.label} ${stock.price.toFixed(2)}`, pad, 34);
  ctx.font = "15px system-ui";
  const planLabels = [
    stock.trigger !== null && stock.trigger !== undefined ? `二次确认 ${stock.trigger.toFixed(2)}` : null,
    stock.invalid !== null && stock.invalid !== undefined ? `失效 ${stock.invalid.toFixed(2)}` : null,
  ].filter(Boolean);
  ctx.fillText(planLabels.join(" / ") || "有效支撑待形成", pad, 60);

  const labelIndexes = [...new Set([0, Math.floor((rows.length - 1) / 2), rows.length - 1])];
  ctx.fillStyle = "#73807b";
  ctx.font = "12px system-ui";
  labelIndexes.forEach((index) => {
    const label = rows[index]?.date ? formatKlineDate(rows[index].date) : "";
    if (!label) return;
    const x = points[index].x;
    const widthText = ctx.measureText(label).width;
    ctx.fillText(label, Math.max(pad, Math.min(width - pad - widthText, x - widthText / 2)), height - 12);
  });
}

function periodConfig(period) {
  return {
    daily: { label: "日线" },
    weekly: { label: "周线" },
    monthly: { label: "月线" },
  }[period] || { label: "日线" };
}

function chartSeries(stock, period) {
  const klines = Array.isArray(stock.klines)
    ? stock.klines.filter((item) => item.date && item.close !== null && item.close !== undefined)
    : [];
  if (klines.length) {
    const ranged = klines.filter((item) => {
      const date = normalizeDateValue(item.date);
      return (!chartRange.from || date >= chartRange.from) && (!chartRange.to || date <= chartRange.to);
    });
    return aggregateKlines(ranged, period);
  }

  const values = stock.trend || [];
  if (!values.length) {
    return [];
  }
  if (period === "daily") {
    return values.map((close) => ({ date: null, close }));
  }
  const chunkSize = period === "weekly" ? 5 : 21;
  const result = [];
  for (let index = 0; index < values.length; index += chunkSize) {
    const chunk = values.slice(index, index + chunkSize);
    result.push({ date: null, close: chunk[chunk.length - 1] });
  }
  return result;
}

function aggregateKlines(klines, period) {
  if (period === "daily") {
    return klines
      .map((item) => ({ date: normalizeDateValue(item.date), close: Number(item.close) }))
      .filter((item) => item.date && Number.isFinite(item.close));
  }

  const grouped = new Map();
  klines.forEach((item) => {
    const date = parseKlineDate(item.date);
    const close = Number(item.close);
    if (!date || !Number.isFinite(close)) {
      return;
    }
    const key = period === "weekly" ? weekKey(date) : monthKey(date);
    grouped.set(key, { date: normalizeDateValue(item.date), close });
  });
  return [...grouped.values()];
}

function normalizeDateValue(value) {
  const text = String(value || "");
  const match = text.match(/^(\d{4})-?(\d{2})-?(\d{2})$/);
  return match ? `${match[1]}-${match[2]}-${match[3]}` : "";
}

function stockDateBounds(stock) {
  const dates = (stock.klines || []).map((item) => normalizeDateValue(item.date)).filter(Boolean).sort();
  return dates.length ? { min: dates[0], max: dates[dates.length - 1] } : null;
}

function shiftDate(isoDate, amount, unit = "day") {
  const date = parseKlineDate(isoDate);
  if (!date) return isoDate;
  if (unit === "month") date.setMonth(date.getMonth() + amount);
  else date.setDate(date.getDate() + amount);
  return date.toISOString().slice(0, 10);
}

function initializeChartRange(stock) {
  const bounds = stockDateBounds(stock);
  if (!bounds) {
    chartRange = { from: null, to: null };
    return;
  }
  chartDateFrom.min = bounds.min;
  chartDateFrom.max = bounds.max;
  chartDateTo.min = bounds.min;
  chartDateTo.max = bounds.max;
  if (chartRangeStockCode !== stock.code) {
    chartRangeStockCode = stock.code;
    chartRange.to = bounds.max;
    chartRange.from = shiftDate(bounds.max, -6, "month");
    if (chartRange.from < bounds.min) chartRange.from = bounds.min;
    rangePresetButtons.forEach((button) => button.classList.toggle("active", button.dataset.rangeMonths === "6"));
  }
  syncChartRangeControls();
}

function syncChartRangeControls() {
  if (chartDateFrom) chartDateFrom.value = chartRange.from || "";
  if (chartDateTo) chartDateTo.value = chartRange.to || "";
  if (chartRangeNote && chartRange.from && chartRange.to) {
    chartRangeNote.textContent = `${chartRange.from} 至 ${chartRange.to} · 拖动图表可平移`;
  }
}

function setChartRange(from, to) {
  const bounds = currentStock ? stockDateBounds(currentStock) : null;
  if (!bounds) return;
  let nextFrom = from || bounds.min;
  let nextTo = to || bounds.max;
  if (nextFrom < bounds.min) nextFrom = bounds.min;
  if (nextTo > bounds.max) nextTo = bounds.max;
  if (nextFrom > nextTo) [nextFrom, nextTo] = [nextTo, nextFrom];
  chartRange = { from: nextFrom, to: nextTo };
  syncChartRangeControls();
  drawChart(currentStock);
}

function parseKlineDate(value) {
  const text = String(value || "");
  const match = text.match(/^(\d{4})-?(\d{2})-?(\d{2})$/);
  if (!match) {
    return null;
  }
  return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
}

function weekKey(date) {
  const target = new Date(date);
  const day = target.getDay() || 7;
  target.setDate(target.getDate() + 4 - day);
  const yearStart = new Date(target.getFullYear(), 0, 1);
  const week = Math.ceil(((target - yearStart) / 86400000 + 1) / 7);
  return `${target.getFullYear()}-W${String(week).padStart(2, "0")}`;
}

function monthKey(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function drawEmptyChart(stock) {
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#fbfcfb";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "#e5ebe7";
  ctx.lineWidth = 1;
  for (let i = 0; i < 5; i += 1) {
    const y = 42 + i * ((height - 84) / 4);
    ctx.beginPath();
    ctx.moveTo(42, y);
    ctx.lineTo(width - 42, y);
    ctx.stroke();
  }
  ctx.fillStyle = "#18211f";
  ctx.font = "24px system-ui";
  ctx.fillText(`${stock.name}`, 42, 54);
  ctx.fillStyle = "#64716c";
  ctx.font = "17px system-ui";
  ctx.fillText("等待真实日线、成交量和板块数据接入后生成结构图", 42, 92);
}

function tradeSummary(stock) {
  if (stock.hasScore === false) {
    if (stock.price !== null && stock.price !== undefined) {
      const quote = stock.quote || {};
      const pct = quote.pctChange === null || quote.pctChange === undefined ? "待计算" : `${quote.pctChange}%`;
      const turnover = quote.turnoverRate === null || quote.turnoverRate === undefined ? "待计算" : `${quote.turnoverRate}%`;
      return `低频行情：当前价 ${stock.price.toFixed(2)}，涨跌幅 ${pct}，换手率 ${turnover}；计划低吸区、回收确认价和失效价待日线结构计算。`;
    }
    return "当前价、计划低吸区、回收确认价和失效价均待真实行情接入后计算。";
  }
  const hasTrigger = stock.trigger !== null && stock.trigger !== undefined;
  const hasInvalid = stock.invalid !== null && stock.invalid !== undefined;
  const triggerDistance = hasTrigger ? ((stock.trigger - stock.price) / stock.price) * 100 : null;
  const riskDistance = hasInvalid ? ((stock.price - stock.invalid) / stock.price) * 100 : null;
  const trial = stock.trialRange;
  const hasTrial = trial?.low !== null && trial?.low !== undefined && trial?.high !== null && trial?.high !== undefined;
  const trialText = hasTrial ? `计划低吸区 ${trial.low.toFixed(2)}-${trial.high.toFixed(2)}，` : "有效支撑待形成，";
  const triggerText = hasTrigger
    ? `二次确认价 ${stock.trigger.toFixed(2)}${triggerDistance >= 0 ? `，距确认约 ${triggerDistance.toFixed(1)}%` : "，原确认价已过期"}`
    : "二次确认价待形成";
  const riskText = hasInvalid ? `失效价 ${stock.invalid.toFixed(2)}，风险距离约 ${riskDistance.toFixed(1)}%` : "失效位待形成";
  return `当前价 ${stock.price.toFixed(2)}，${trialText}${triggerText}；${riskText}。`;
}

function drawLine(points, color, lineWidth) {
  ctx.beginPath();
  ctx.strokeStyle = color;
  ctx.lineWidth = lineWidth;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  points.forEach((point, index) => {
    if (index === 0) {
      ctx.moveTo(point.x, point.y);
    } else {
      ctx.lineTo(point.x, point.y);
    }
  });
  ctx.stroke();
}

function movingAverage(data, windowSize) {
  return data.map((_, index) => {
    const start = Math.max(0, index - windowSize + 1);
    const slice = data.slice(start, index + 1);
    return slice.reduce((sum, item) => sum + item, 0) / slice.length;
  });
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  evaluateQuery(input.value, true, true);
});

periodButtons.forEach((button) => {
  button.addEventListener("click", () => {
    activePeriod = button.dataset.period || "daily";
    periodButtons.forEach((item) => item.classList.toggle("active", item === button));
    if (currentStock) {
      drawChart(currentStock);
    }
  });
});

[chartDateFrom, chartDateTo].forEach((control) => {
  control?.addEventListener("change", () => {
    rangePresetButtons.forEach((button) => button.classList.remove("active"));
    setChartRange(chartDateFrom.value, chartDateTo.value);
  });
});

rangePresetButtons.forEach((button) => {
  button.addEventListener("click", () => {
    if (!currentStock) return;
    const bounds = stockDateBounds(currentStock);
    if (!bounds) return;
    const months = button.dataset.rangeMonths;
    const from = months === "all" ? bounds.min : shiftDate(bounds.max, -Number(months), "month");
    rangePresetButtons.forEach((item) => item.classList.toggle("active", item === button));
    setChartRange(from, bounds.max);
  });
});

canvas.addEventListener("pointerdown", (event) => {
  if (!currentStock || !chartRange.from || !chartRange.to) return;
  chartDrag = {
    startX: event.clientX,
    from: chartRange.from,
    to: chartRange.to,
  };
  canvas.classList.add("dragging");
  canvas.setPointerCapture?.(event.pointerId);
});

canvas.addEventListener("pointermove", (event) => {
  if (!chartDrag || !currentStock) return;
  const start = parseKlineDate(chartDrag.from);
  const end = parseKlineDate(chartDrag.to);
  if (!start || !end) return;
  const spanDays = Math.max(1, Math.round((end - start) / 86400000));
  const shiftDays = Math.round(((chartDrag.startX - event.clientX) / canvas.clientWidth) * spanDays);
  setChartRange(shiftDate(chartDrag.from, shiftDays), shiftDate(chartDrag.to, shiftDays));
});

function stopChartDrag(event) {
  if (!chartDrag) return;
  chartDrag = null;
  canvas.classList.remove("dragging");
  canvas.releasePointerCapture?.(event.pointerId);
}

canvas.addEventListener("pointerup", stopChartDrag);
canvas.addEventListener("pointercancel", stopChartDrag);

async function fetchEvaluation(
  query,
  refreshQuote = false,
  refreshFundamental = false,
  refreshKline = false,
) {
  const refreshParam = refreshQuote ? "&refresh=1" : "";
  const fundamentalParam = refreshFundamental ? "&fundamental=1" : "";
  const klineParam = refreshKline ? "&kline=1" : "";
  return fetchJsonWithSnapshot(`/api/evaluate?q=${encodeURIComponent(query)}${refreshParam}${fundamentalParam}${klineParam}`);
}

async function fetchProviderStatus() {
  return fetchJsonWithSnapshot("/api/provider");
}

async function fetchWatchlist() {
  return fetchJsonWithSnapshot("/api/watchlist");
}

async function fetchDailyBrief() {
  return fetchJsonWithSnapshot("/api/daily-brief");
}

async function fetchIndustryInsight() {
  return fetchJsonWithSnapshot("/api/industry-insight");
}

async function refreshHomePayload() {
  const response = await fetch("/api/home/refresh", {
    method: "POST",
  });
  const payload = await response.json();
  if (!response.ok || !payload.ok) {
    throw new Error(payload.reason || `API ${response.status}`);
  }
  return payload;
}

async function refreshWatchlistFundamentals() {
  const response = await fetch("/api/watchlist/refresh-fundamentals", {
    method: "POST",
  });
  const payload = await response.json();
  if (!response.ok || !payload.ok) {
    throw new Error(payload.reason || `API ${response.status}`);
  }
  return payload;
}

async function fetchSectorRankings() {
  return fetchJsonWithSnapshot("/api/sector-rankings");
}

async function fetchSectorDetail(group) {
  return fetchJsonWithSnapshot(`/api/sector-detail?group=${encodeURIComponent(group)}`);
}

async function addCurrentStockToWatchlist() {
  if (!currentStock) return;
  const response = await fetch("/api/watchlist", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ stock: currentStock }),
  });
  const payload = await response.json();
  if (!response.ok || !payload.ok) {
    throw new Error(payload.reason || `API ${response.status}`);
  }
  return payload;
}

async function removeStockFromWatchlist(code) {
  const response = await fetch(`/api/watchlist?code=${encodeURIComponent(code)}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new Error(`API ${response.status}`);
  }
  return response.json();
}

async function fetchMarketSentiment(refresh = false) {
  const url = refresh ? "/api/market-sentiment?refresh=1" : "/api/market-sentiment";
  return fetchJsonWithSnapshot(url);
}

async function refreshMarketSentiment() {
  if (refreshSentimentButton) {
    refreshSentimentButton.disabled = true;
    refreshSentimentButton.textContent = "刷新中";
  }
  try {
    latestMarketSentiment = await fetchMarketSentiment(true);
    renderMarketSentiment(latestMarketSentiment);
    for (let index = 0; index < 8 && latestMarketSentiment?.refreshing; index += 1) {
      await new Promise((resolve) => setTimeout(resolve, 5000));
      latestMarketSentiment = await fetchMarketSentiment(false);
      renderMarketSentiment(latestMarketSentiment);
    }
  } catch (error) {
    latestMarketSentiment = {
      ok: false,
      reason: "全市场情绪接口暂不可用，稍后可重试。",
    };
    renderMarketSentiment(latestMarketSentiment);
  }
}

async function evaluateQuery(
  query,
  syncUrl = false,
  refreshQuote = false,
  refreshFundamental = false,
  refreshKline = false,
) {
  showDetailView();
  searchStatus.textContent = refreshKline
    ? "正在补齐当前股票完整日K，请等待限速队列..."
    : refreshFundamental
    ? "正在刷新当前股票基本面..."
    : refreshQuote
      ? "正在刷新最新行情并评估..."
      : "正在读取本地缓存/后端评估结果...";
  let result;

  try {
    result = await fetchEvaluation(query, refreshQuote, refreshFundamental, refreshKline);
    if (!refreshQuote && !refreshFundamental && result?.status?.includes("应更新至")) {
      searchStatus.textContent = "缓存行情偏旧，正在补一次最新行情...";
      result = await fetchEvaluation(query, true, false);
    }
    const [providerResult, sentimentResult] = await Promise.allSettled([
      fetchProviderStatus(),
      fetchMarketSentiment(false),
    ]);
    latestProviderStatus = providerResult.status === "fulfilled" ? providerResult.value : null;
    latestMarketSentiment = sentimentResult.status === "fulfilled" ? sentimentResult.value : null;
  } catch (error) {
    result = findStock(query);
    result.status = "本地评分服务未启动或连接中断。请确认4173服务正在运行后刷新页面，当前内容仅为离线占位，不代表股票数据缺失。";
    latestProviderStatus = null;
    latestMarketSentiment = null;
  }

  searchStatus.textContent = result.status;
  renderStock(result.stock);

  if (syncUrl && query.trim()) {
    const url = new URL(window.location.href);
    url.searchParams.set("stock", query.trim());
    window.history.replaceState({}, "", url);
  }
  updateWatchlistButton();
  return result;
}

if (refreshSentimentButton) {
  refreshSentimentButton.addEventListener("click", refreshMarketSentiment);
}

refreshDailyBriefButton?.addEventListener("click", loadDailyBrief);
refreshIndustryInsightButton?.addEventListener("click", loadIndustryInsight);
refreshHomeButton?.addEventListener("click", refreshHomeData);

document.querySelector("#briefActionItems")?.addEventListener("click", (event) => {
  const button = event.target.closest("[data-open-stock]");
  if (!button?.dataset.openStock) return;
  input.value = button.dataset.openStock;
  evaluateQuery(button.dataset.openStock, true, true);
});

refreshFundamentalButton?.addEventListener("click", async () => {
  if (!currentStock?.code) return;
  refreshFundamentalButton.disabled = true;
  refreshFundamentalButton.textContent = "刷新中";
  try {
    await evaluateQuery(currentStock.code, true, false, true);
    await loadWatchlist();
  } finally {
    refreshFundamentalButton.textContent = "刷新基本面";
    updateWatchlistButton();
  }
});

refreshKlineButton?.addEventListener("click", async () => {
  if (!currentStock?.code) return;
  const code = currentStock.code;
  refreshKlineButton.disabled = true;
  refreshKlineButton.textContent = "补齐中";
  if (watchlistActionStatus) {
    watchlistActionStatus.textContent = "正在请求当前股票完整日K...";
  }
  try {
    const result = await evaluateQuery(code, true, false, false, true);
    const refreshedStock = result?.stock || {};
    const latestDate = refreshedStock.quote?.scoreDate || refreshedStock.quote?.quoteTime;
    const stillStale = Boolean(refreshedStock.metrics?.dataStale);
    if (watchlistActionStatus) {
      watchlistActionStatus.textContent = stillStale
        ? "完整日K仍有缺口，请稍后重试"
        : `完整日K已补齐${latestDate ? `至 ${formatKlineDate(latestDate)}` : ""}`;
    }
    if (isCurrentStockInWatchlist()) {
      await addCurrentStockToWatchlist();
    }
    await loadWatchlist();
  } catch (error) {
    if (watchlistActionStatus) {
      watchlistActionStatus.textContent = error.message || "K线补齐失败";
    }
  } finally {
    refreshKlineButton.disabled = false;
    refreshKlineButton.textContent = "补齐K线";
    updateWatchlistButton();
  }
});

refreshWatchlistFundamentalsButton?.addEventListener("click", async () => {
  refreshWatchlistFundamentalsButton.disabled = true;
  refreshWatchlistFundamentalsButton.textContent = "刷新中";
  if (watchlistSummary) {
    watchlistSummary.textContent = "正在刷新选股池基本面...";
  }
  try {
    const payload = await refreshWatchlistFundamentals();
    renderWatchlist(payload.items || [], payload.battleGroups || []);
    if (watchlistSummary) {
      const okCount = (payload.refreshResults || []).filter((item) => item.fundamentalOk).length;
      watchlistSummary.textContent = `${payload.count || 0} 只跟踪 · 基本面刷新 ${okCount}/${(payload.refreshResults || []).length}`;
    }
  } catch (error) {
    if (watchlistSummary) {
      watchlistSummary.textContent = error.message || "刷新失败";
    }
  } finally {
    refreshWatchlistFundamentalsButton.disabled = false;
    refreshWatchlistFundamentalsButton.textContent = "刷新基本面";
  }
});

backToWatchlist?.addEventListener("click", () => {
  showWatchlistView();
  loadWatchlist();
});

watchlistToggle?.addEventListener("click", async () => {
  if (!currentStock?.code) return;
  watchlistToggle.disabled = true;
  if (watchlistActionStatus) {
    watchlistActionStatus.textContent = "处理中...";
  }
  try {
    if (isCurrentStockInWatchlist()) {
      const payload = await removeStockFromWatchlist(currentStock.code);
      renderWatchlist(payload.items || [], payload.battleGroups || []);
      if (watchlistActionStatus) {
        watchlistActionStatus.textContent = "已移出选股池";
      }
    } else {
      const payload = await addCurrentStockToWatchlist();
      renderWatchlist(payload.items || [], payload.battleGroups || []);
      if (watchlistActionStatus) {
        watchlistActionStatus.textContent = "已加入选股池";
      }
    }
  } catch (error) {
    if (watchlistActionStatus) {
      watchlistActionStatus.textContent = error.message || "操作失败";
    }
  } finally {
    updateWatchlistButton();
  }
});

watchlistRows?.addEventListener("click", async (event) => {
  const removeButton = event.target.closest("[data-remove-stock]");
  if (removeButton) {
    const payload = await removeStockFromWatchlist(removeButton.dataset.removeStock);
    renderWatchlist(payload.items || [], payload.battleGroups || []);
    return;
  }
  const openButton = event.target.closest("[data-open-stock]");
  if (openButton) {
    input.value = openButton.dataset.openStock;
    evaluateQuery(openButton.dataset.openStock, true, true);
  }
});

industryInsightView?.addEventListener("click", (event) => {
  const sectorButton = event.target.closest("[data-open-sector]");
  if (sectorButton) {
    loadSectorDetail(sectorButton.dataset.openSector);
    return;
  }
  const openButton = event.target.closest("[data-open-stock]");
  if (!openButton) return;
  input.value = openButton.dataset.openStock;
  evaluateQuery(openButton.dataset.openStock, true, true);
});

sectorRankView?.addEventListener("click", (event) => {
  const closeButton = event.target.closest("[data-close-sector-detail]");
  if (closeButton) {
    sectorDetail?.classList.add("hidden");
    return;
  }
  const sectorButton = event.target.closest("[data-open-sector]");
  if (sectorButton) {
    loadSectorDetail(sectorButton.dataset.openSector);
    return;
  }
  const openButton = event.target.closest("[data-open-stock]");
  if (!openButton) return;
  input.value = openButton.dataset.openStock;
  evaluateQuery(openButton.dataset.openStock, true, true);
});

const initialStock = new URLSearchParams(window.location.search).get("stock");
loadWatchlist().then(() => {
  if (!initialStock) {
    showWatchlistView();
  }
});
loadDailyBrief();
loadIndustryInsight();
loadSectorRankings();
if (initialStock) {
  input.value = initialStock;
  evaluateQuery(initialStock);
} else {
  input.value = "";
  showWatchlistView();
}

window.stockApp = {
  findStock,
  evaluateQuery,
  refreshMarketSentiment,
  renderStock,
};

const pwaStatus = document.querySelector("#pwaStatus");
function updatePwaStatus() {
  if (!pwaStatus) return;
  pwaStatus.textContent = navigator.onLine ? "在线，优先读取最新快照" : "离线，正在使用最后有效数据";
  pwaStatus.classList.toggle("offline", !navigator.onLine);
}
window.addEventListener("online", updatePwaStatus);
window.addEventListener("offline", updatePwaStatus);
updatePwaStatus();
loadMobileSnapshot().then(renderSnapshotFreshness).catch(() => null);

window.addEventListener("focus", checkLatestSnapshot);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") checkLatestSnapshot();
});
window.setInterval(checkLatestSnapshot, 15 * 60 * 1000);

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("../service-worker.js").catch(() => null);
  });
}

/*
  后续真实数据层建议：
  1. searchStock(query) 只查本地股票基础表，不直接打外部行情接口。
  2. refreshDailyData() 在收盘后批量更新，落地到数据库或 json 缓存。
  3. RateLimiter 控制外部接口并发、间隔和失败退避，避免 IP 被封。
  4. FundamentalAdapter / QuoteAdapter / SectorAdapter 分离，方便替换数据源。
*/
