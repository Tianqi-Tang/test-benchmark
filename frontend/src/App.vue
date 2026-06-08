<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue';

type ModelConfig = {
  id: number;
  name: string;
  provider: string;
  model: string;
  baseUrl: string | null;
  apiKeyMasked: string;
  capability: string;
  enabled: boolean;
  maxOutputTokens: number;
  lastTestStatus: string | null;
  lastTestLatencyMs: number | null;
  lastTestError: string | null;
  lastTestedAt: string | null;
};

type BenchmarkSet = {
  id: number;
  name: string;
  category: string;
  sourcePath: string | null;
  modality: string;
  questionCount: number;
};

type BenchmarkQuestion = {
  id: number;
  sourceRow: number;
  questionType: string;
  question: string;
  options: string | null;
  answer: string;
};

type EvaluationRun = {
  id: number;
  benchmarkSetId: number;
  benchmarkSetName: string | null;
  status: string;
  totalCount: number;
  completedCount: number;
  correctCount: number;
  accuracy: number;
  errorMessage: string | null;
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
};

type EvaluationResult = {
  id: number;
  modelConfigId: number;
  modelName: string | null;
  question: string | null;
  options: string | null;
  questionType: string | null;
  status: string;
  prompt: string;
  expectedAnswer: string;
  modelAnswer: string | null;
  extractedAnswer: string | null;
  isCorrect: boolean | null;
  score: number | null;
  latencyMs: number | null;
  errorMessage: string | null;
};

type ModelScore = {
  modelConfigId: number;
  modelName: string;
  provider: string;
  model: string;
  capability: string;
  latestRunId: number | null;
  latestRunStatus: string | null;
  benchmarkSetName: string | null;
  latestEvaluatedAt: string | null;
  totalCount: number;
  scoredCount: number;
  correctCount: number;
  accuracy: number;
};

type SessionState = {
  authenticated: boolean;
  authConfigured: boolean;
};

type Capability = 'text' | 'vision';

type ProviderOption = {
  value: string;
  label: string;
  shortLabel: string;
  defaultModel: string;
  modelOptions: string[];
  baseUrl: string;
  defaultCapabilities: Capability[];
};

type CapabilityOption = {
  value: Capability;
  label: string;
};

const tabs = [
  { id: 'models', label: '模型配置' },
  { id: 'benchmarks', label: '题集管理' },
  { id: 'runs', label: '评测运行' },
  { id: 'results', label: '结果看板' },
] as const;

type TabId = (typeof tabs)[number]['id'];

const activeTab = ref<TabId>('models');
const models = ref<ModelConfig[]>([]);
const benchmarkSets = ref<BenchmarkSet[]>([]);
const questions = ref<BenchmarkQuestion[]>([]);
const runs = ref<EvaluationRun[]>([]);
const modelScores = ref<ModelScore[]>([]);
const runResults = ref<Record<number, EvaluationResult[]>>({});
const selectedBenchmarkSetId = ref<number | null>(null);
const selectedModelIds = ref<number[]>([]);
const editingModelId = ref<number | null>(null);
const editingQuestionId = ref<number | null>(null);
const benchmarkFileInput = ref<HTMLInputElement | null>(null);
const modelDialogOpen = ref(false);
const runDialogOpen = ref(false);
const detailRunId = ref<number | null>(null);
const expandedResultId = ref<number | null>(null);
const testingModelIds = ref<Set<number>>(new Set());
const authChecked = ref(false);
const authenticated = ref(false);
const loading = ref(false);
const notice = ref('');
const error = ref('');

const loginForm = reactive({
  password: '',
});

const modelForm = reactive({
  name: '',
  provider: 'deepseek',
  model: 'deepseek-v4-pro',
  baseUrl: '',
  apiKey: '',
  clearApiKey: false,
  capabilities: ['text'] as Capability[],
  enabled: true,
  maxOutputTokens: 2048,
});

const questionForm = reactive({
  questionType: 'qa',
  question: '',
  options: '',
  answer: '',
});

const capabilityOptions: CapabilityOption[] = [
  { value: 'text', label: '文本' },
  { value: 'vision', label: '多模态' },
];

const providerOptions: ProviderOption[] = [
  {
    value: 'ant_ling',
    label: '蚂蚁百灵（Ant Ling）',
    shortLabel: '蚂蚁百灵',
    defaultModel: 'AntAngelMed',
    modelOptions: ['AntAngelMed', 'Ling-2.6-flash', 'Ling-2.6-1T', 'Ring-2.6-1T'],
    baseUrl: 'https://api.ant-ling.com/v1',
    defaultCapabilities: ['text'],
  },
  {
    value: 'deepseek',
    label: 'DeepSeek',
    shortLabel: 'DeepSeek',
    defaultModel: 'deepseek-v4-pro',
    modelOptions: ['deepseek-v4-pro', 'deepseek-v4-flash', 'deepseek-chat', 'deepseek-reasoner'],
    baseUrl: 'https://api.deepseek.com',
    defaultCapabilities: ['text'],
  },
  {
    value: 'qwen',
    label: '阿里云千问（Qwen）',
    shortLabel: '千问',
    defaultModel: 'qwen3.7-plus',
    modelOptions: [
      'qwen3.7-plus',
      'qwen-max',
      'qwen-plus',
      'qwen-turbo',
      'qwen3.5-plus',
      'qwen3.5-flash',
      'qwen3-vl-plus',
      'qwen3-vl-flash',
      'qwen3-vl-plus-2025-12-19',
      'qwen-vl-plus',
      'qwen-vl-plus-latest',
      'qwen-vl-max',
      'qwen-vl-max-latest',
    ],
    baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    defaultCapabilities: ['text'],
  },
  {
    value: 'openai_responses',
    label: 'ChatGPT（OpenAI）',
    shortLabel: 'ChatGPT',
    defaultModel: 'gpt-5.5',
    modelOptions: ['gpt-5.5'],
    baseUrl: 'https://api.openai.com/v1',
    defaultCapabilities: ['text', 'vision'],
  },
  {
    value: 'gemini',
    label: 'Google Gemini',
    shortLabel: 'Gemini',
    defaultModel: 'gemini-3.5-flash',
    modelOptions: ['gemini-3.5-flash', 'gemini-3.5-pro', 'gemini-2.0-flash'],
    baseUrl: 'https://generativelanguage.googleapis.com',
    defaultCapabilities: ['text', 'vision'],
  },
];

const modelPresetNames = new Set(providerOptions.flatMap((provider) => provider.modelOptions));

let pollTimer: number | undefined;
const appBasePath = import.meta.env.BASE_URL ?? '/';

const hasActiveRuns = computed(() => runs.value.some((run) => run.status === 'pending' || run.status === 'running'));
const runnableModels = computed(() => models.value.filter((model) => model.enabled && modelSupportsCapability(model, 'text')));
const isEditingModel = computed(() => editingModelId.value !== null);
const selectedProvider = computed(() => providerOption(modelForm.provider) ?? providerOptions[0]);
const modelOptionsForForm = computed(() => {
  const options = selectedProvider.value.modelOptions;
  return modelForm.model && !options.includes(modelForm.model) ? [modelForm.model, ...options] : options;
});
const modelDialogTitle = computed(() => (isEditingModel.value ? '编辑模型' : '新增模型'));
const detailRun = computed(() => runs.value.find((run) => run.id === detailRunId.value) ?? null);
const scoredModelScores = computed(() => modelScores.value.filter((score) => score.scoredCount > 0));
const evaluatedModelScores = computed(() => modelScores.value.filter((score) => score.latestRunId));
const sortedModelScores = computed(() => {
  return [...modelScores.value].sort((left, right) => {
    if (left.scoredCount && right.scoredCount) {
      if (right.accuracy !== left.accuracy) return right.accuracy - left.accuracy;
      return right.scoredCount - left.scoredCount;
    }
    if (left.scoredCount) return -1;
    if (right.scoredCount) return 1;
    return left.modelName.localeCompare(right.modelName, 'zh-Hans-CN');
  });
});
const averageModelAccuracy = computed(() => {
  if (!scoredModelScores.value.length) return 0;
  const total = scoredModelScores.value.reduce((sum, score) => sum + score.accuracy, 0);
  return total / scoredModelScores.value.length;
});
const bestModelScore = computed(() => {
  return scoredModelScores.value.reduce<ModelScore | null>((best, score) => {
    if (!best || score.accuracy > best.accuracy) return score;
    return best;
  }, null);
});

onMounted(checkSession);

onUnmounted(() => {
  if (pollTimer) window.clearInterval(pollTimer);
});

async function api<T>(url: string, options?: RequestInit): Promise<T> {
  const isFormData = options?.body instanceof FormData;
  const response = await fetch(apiUrl(url), {
    credentials: 'include',
    headers: { ...(isFormData ? {} : { 'Content-Type': 'application/json' }), ...(options?.headers ?? {}) },
    ...options,
  });
  if (response.status === 401) {
    authenticated.value = false;
    stopPolling();
  }
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      // keep HTTP status
    }
    throw new Error(detail);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}

function apiUrl(url: string) {
  if (!url.startsWith('/api')) return url;
  const base = appBasePath.endsWith('/') ? appBasePath.slice(0, -1) : appBasePath;
  return `${base}${url}`;
}

async function checkSession() {
  loading.value = true;
  error.value = '';
  try {
    const session = await api<SessionState>('/api/auth/session');
    authenticated.value = session.authenticated;
    authChecked.value = true;
    if (!session.authConfigured) {
      error.value = '服务端未配置登录密码，请设置 TEST_BENCHMARK_AUTH_PASSWORD';
      return;
    }
    if (session.authenticated) {
      await refreshAll();
      startPolling();
    }
  } catch (err) {
    authChecked.value = true;
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    loading.value = false;
  }
}

async function loginUser() {
  await withLoading(async () => {
    const session = await api<SessionState>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ password: loginForm.password }),
    });
    authenticated.value = session.authenticated;
    loginForm.password = '';
    notice.value = '已登录';
    await refreshAll();
    startPolling();
  });
}

async function logoutUser() {
  await withLoading(async () => {
    await api<SessionState>('/api/auth/logout', { method: 'POST' });
    authenticated.value = false;
    stopPolling();
    notice.value = '';
    clearWorkspaceState();
  });
}

function startPolling() {
  stopPolling();
  pollTimer = window.setInterval(refreshRunsAndResults, 3000);
}

function stopPolling() {
  if (pollTimer) {
    window.clearInterval(pollTimer);
    pollTimer = undefined;
  }
}

function clearWorkspaceState() {
  models.value = [];
  benchmarkSets.value = [];
  questions.value = [];
  runs.value = [];
  modelScores.value = [];
  runResults.value = {};
  selectedBenchmarkSetId.value = null;
  selectedModelIds.value = [];
  detailRunId.value = null;
  expandedResultId.value = null;
  modelDialogOpen.value = false;
  runDialogOpen.value = false;
}

async function refreshAll() {
  await withLoading(async () => {
    await Promise.all([loadModels(), loadBenchmarkSets(), loadRuns(), loadModelScores()]);
  });
}

async function refreshRunsAndResults() {
  if (!hasActiveRuns.value) return;
  try {
    await loadRuns();
    await loadModelScores();
    if (detailRunId.value) {
      await loadRunResults(detailRunId.value);
    }
  } catch {
    // polling should not steal focus with repeated errors
  }
}

async function loadModels() {
  models.value = await api<ModelConfig[]>('/api/models');
}

async function loadBenchmarkSets() {
  benchmarkSets.value = await api<BenchmarkSet[]>('/api/benchmark-sets');
  if (!selectedBenchmarkSetId.value && benchmarkSets.value.length) {
    selectedBenchmarkSetId.value = benchmarkSets.value[0].id;
  }
}

async function loadQuestions(benchmarkSetId: number) {
  questions.value = await api<BenchmarkQuestion[]>(`/api/benchmark-sets/${benchmarkSetId}/questions?limit=500`);
}

async function loadRuns() {
  runs.value = await api<EvaluationRun[]>('/api/evaluation-runs');
}

async function loadModelScores() {
  modelScores.value = await api<ModelScore[]>('/api/dashboard/model-scores');
}

async function loadRunResults(runId: number) {
  const rows = await api<EvaluationResult[]>(`/api/evaluation-runs/${runId}/results`);
  runResults.value = { ...runResults.value, [runId]: rows };
}

function applyProviderPreset() {
  const preset = providerOption(modelForm.provider);
  if (!preset) return;
  modelForm.model = preset.defaultModel;
  modelForm.baseUrl = preset.baseUrl;
  modelForm.capabilities = defaultCapabilitiesForModel(preset.value, preset.defaultModel);
  if (!modelForm.name || modelPresetNames.has(modelForm.name)) {
    modelForm.name = preset.defaultModel;
  }
}

function applyModelPreset() {
  modelForm.capabilities = defaultCapabilitiesForModel(modelForm.provider, modelForm.model);
  if (!modelForm.name || modelPresetNames.has(modelForm.name)) {
    modelForm.name = modelForm.model;
  }
}

function openCreateModelDialog() {
  resetModelForm();
  modelDialogOpen.value = true;
}

function closeModelDialog() {
  modelDialogOpen.value = false;
  resetModelForm();
}

function toggleCapability(capability: Capability, event: Event) {
  const checked = (event.target as HTMLInputElement).checked;
  if (checked && !modelForm.capabilities.includes(capability)) {
    modelForm.capabilities = [...modelForm.capabilities, capability];
  } else if (!checked) {
    modelForm.capabilities = modelForm.capabilities.filter((value) => value !== capability);
  }
}

async function saveModel() {
  if (!modelForm.capabilities.length) {
    error.value = '请至少选择一种模型能力';
    return;
  }
  await withLoading(async () => {
    const payload = {
      name: modelForm.name,
      provider: normalizeProviderValue(modelForm.provider),
      model: modelForm.model,
      baseUrl: modelForm.baseUrl || null,
      apiKey: modelForm.apiKey || undefined,
      clearApiKey: modelForm.clearApiKey,
      capability: serializeCapabilities(modelForm.capabilities),
      enabled: modelForm.enabled,
      maxOutputTokens: modelForm.maxOutputTokens,
    };
    if (editingModelId.value) {
      await api<ModelConfig>(`/api/models/${editingModelId.value}`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      });
      notice.value = '模型配置已更新';
    } else {
      await api<ModelConfig>('/api/models', {
        method: 'POST',
        body: JSON.stringify({
          ...payload,
          apiKey: modelForm.apiKey || null,
          clearApiKey: undefined,
        }),
      });
      notice.value = '模型配置已保存';
    }
    modelForm.apiKey = '';
    modelForm.clearApiKey = false;
    editingModelId.value = null;
    modelDialogOpen.value = false;
    await loadModels();
  });
}

function editModel(model: ModelConfig) {
  editingModelId.value = model.id;
  modelForm.name = model.name;
  modelForm.provider = normalizeProviderValue(model.provider);
  modelForm.model = model.model;
  modelForm.baseUrl = model.baseUrl ?? '';
  modelForm.apiKey = '';
  modelForm.clearApiKey = false;
  modelForm.capabilities = capabilitiesFromValue(model.capability);
  modelForm.enabled = model.enabled;
  modelForm.maxOutputTokens = model.maxOutputTokens;
  activeTab.value = 'models';
  modelDialogOpen.value = true;
}

function resetModelForm() {
  editingModelId.value = null;
  modelForm.name = '';
  modelForm.provider = 'deepseek';
  modelForm.model = 'deepseek-v4-pro';
  modelForm.baseUrl = '';
  modelForm.apiKey = '';
  modelForm.clearApiKey = false;
  modelForm.capabilities = ['text'];
  modelForm.enabled = true;
  modelForm.maxOutputTokens = 2048;
  error.value = '';
  notice.value = '';
}

async function testModel(modelId: number) {
  if (testingModelIds.value.has(modelId)) return;
  testingModelIds.value = new Set([...testingModelIds.value, modelId]);
  error.value = '';
  notice.value = '';
  try {
    const result = await api<{ ok: boolean; message: string; responseText?: string }>(`/api/models/${modelId}/test`, {
      method: 'POST',
    });
    notice.value = result.ok ? `连接成功：${result.responseText ?? result.message}` : result.message;
    await loadModels();
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
    await loadModels();
  } finally {
    const next = new Set(testingModelIds.value);
    next.delete(modelId);
    testingModelIds.value = next;
  }
}

function openBenchmarkFilePicker() {
  benchmarkFileInput.value?.click();
}

async function importBenchmarkFile(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = '';
  if (!file) return;
  await withLoading(async () => {
    const formData = new FormData();
    formData.append('file', file);
    const result = await api<{ importedSets: BenchmarkSet[]; totalQuestions: number }>(
      '/api/benchmark-sets/import/jsonl',
      {
        method: 'POST',
        headers: {},
        body: formData,
      },
    );
    notice.value = `导入完成：${result.importedSets[0]?.name ?? file.name}，${result.totalQuestions} 道题`;
    await loadBenchmarkSets();
    const imported = result.importedSets[0];
    if (imported) {
      await viewQuestions(imported.id);
    }
  });
}

async function viewQuestions(id: number) {
  selectedBenchmarkSetId.value = id;
  editingQuestionId.value = null;
  await withLoading(async () => {
    await loadQuestions(id);
  });
}

function editQuestion(question: BenchmarkQuestion) {
  editingQuestionId.value = question.id;
  questionForm.questionType = question.questionType;
  questionForm.question = question.question;
  questionForm.options = question.options ?? '';
  questionForm.answer = question.answer;
}

function cancelQuestionEdit() {
  editingQuestionId.value = null;
  questionForm.questionType = 'qa';
  questionForm.question = '';
  questionForm.options = '';
  questionForm.answer = '';
}

async function saveQuestion(questionId: number) {
  await withLoading(async () => {
    await api<BenchmarkQuestion>(`/api/benchmark-questions/${questionId}`, {
      method: 'PUT',
      body: JSON.stringify({
        questionType: questionForm.questionType,
        question: questionForm.question,
        options: questionForm.options || null,
        answer: questionForm.answer,
      }),
    });
    notice.value = '题目已更新';
    const setId = selectedBenchmarkSetId.value;
    cancelQuestionEdit();
    if (setId) await loadQuestions(setId);
  });
}

async function deleteQuestion(questionId: number) {
  await withLoading(async () => {
    await api<void>(`/api/benchmark-questions/${questionId}`, { method: 'DELETE' });
    notice.value = '题目已删除';
    const setId = selectedBenchmarkSetId.value;
    if (setId) await Promise.all([loadQuestions(setId), loadBenchmarkSets()]);
  });
}

function toggleModelSelection(modelId: number, checked: boolean) {
  if (checked && !selectedModelIds.value.includes(modelId)) {
    selectedModelIds.value = [...selectedModelIds.value, modelId];
  } else if (!checked) {
    selectedModelIds.value = selectedModelIds.value.filter((id) => id !== modelId);
  }
}

function onModelSelectionChange(modelId: number, event: Event) {
  toggleModelSelection(modelId, (event.target as HTMLInputElement).checked);
}

function openRunDialog() {
  if (!selectedBenchmarkSetId.value) {
    error.value = '请先选择题集';
    return;
  }
  if (!runnableModels.value.length) {
    error.value = '请先配置至少一个支持文本能力的已启用模型';
    return;
  }
  const runnableIds = new Set(runnableModels.value.map((model) => model.id));
  selectedModelIds.value = selectedModelIds.value.filter((id) => runnableIds.has(id));
  if (!selectedModelIds.value.length) {
    selectedModelIds.value = runnableModels.value.map((model) => model.id);
  }
  error.value = '';
  notice.value = '';
  runDialogOpen.value = true;
}

function closeRunDialog() {
  runDialogOpen.value = false;
}

async function createRun() {
  if (!selectedModelIds.value.length) {
    error.value = '请至少选择一个模型';
    return;
  }
  await withLoading(async () => {
    const run = await api<EvaluationRun>('/api/evaluation-runs', {
      method: 'POST',
      body: JSON.stringify({
        benchmarkSetId: selectedBenchmarkSetId.value,
        modelConfigIds: selectedModelIds.value,
      }),
    });
    detailRunId.value = run.id;
    activeTab.value = 'runs';
    runDialogOpen.value = false;
    notice.value = `评测已启动：#${run.id}`;
    await loadRuns();
    await Promise.all([loadRunResults(run.id), loadModelScores()]);
  });
}

async function openRunDetails(runId: number) {
  detailRunId.value = runId;
  expandedResultId.value = null;
  await withLoading(async () => {
    await loadRunResults(runId);
  });
}

function closeRunDetails() {
  detailRunId.value = null;
  expandedResultId.value = null;
}

async function stopRun(runId: number) {
  await withLoading(async () => {
    const run = await api<EvaluationRun>(`/api/evaluation-runs/${runId}/stop`, { method: 'POST' });
    notice.value = `评测已结束：#${run.id}`;
    await loadRuns();
    await loadModelScores();
    if (detailRunId.value === run.id) {
      await loadRunResults(run.id);
    }
  });
}

function toggleResultRecord(resultId: number) {
  expandedResultId.value = expandedResultId.value === resultId ? null : resultId;
}

async function withLoading(task: () => Promise<void>) {
  loading.value = true;
  error.value = '';
  notice.value = '';
  try {
    await task();
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    loading.value = false;
  }
}

function formatPercent(value: number) {
  return `${Math.round(value * 100)}%`;
}

function progressPercent(run: EvaluationRun) {
  if (run.totalCount === 0) return 0;
  return Math.round((run.completedCount / run.totalCount) * 100);
}

function resultsForRun(runId: number) {
  return runResults.value[runId] ?? [];
}

function modelScoreBarWidth(score: ModelScore) {
  return `${Math.max(3, Math.round(score.accuracy * 100))}%`;
}

function modelScoreStatus(score: ModelScore) {
  if (!score.latestRunId) return '未评测';
  if (!score.scoredCount) return '无可评分结果';
  return formatPercent(score.accuracy);
}

function formatStatus(value: string) {
  const labels: Record<string, string> = {
    pending: '等待中',
    running: '运行中',
    completed: '完成',
    failed: '失败',
    stopped: '已结束',
  };
  return labels[value] ?? value;
}

function statusBadgeClass(value: string) {
  const normalized = value || 'pending';
  return `status-badge status-badge-${normalized}`;
}

function formatOptionalStatus(value: string | null) {
  return value ? formatStatus(value) : '-';
}

function formatDateTime(value: string | null) {
  if (!value) return '-';
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value));
}

function formatModelTestStatus(model: ModelConfig) {
  if (!model.lastTestStatus) return '未测试';
  return model.lastTestStatus === 'success' ? '通过' : '失败';
}

function modelTestStatusClass(model: ModelConfig) {
  if (model.lastTestStatus === 'success') return 'ok';
  if (model.lastTestStatus === 'failed') return 'bad';
  return 'muted';
}

function isModelTesting(modelId: number) {
  return testingModelIds.value.has(modelId);
}

function canStopRun(run: EvaluationRun) {
  return run.status === 'pending' || run.status === 'running';
}

function normalizeProviderValue(provider: string) {
  return provider === 'qwen_vision' ? 'qwen' : provider;
}

function providerOption(provider: string) {
  return providerOptions.find((option) => option.value === normalizeProviderValue(provider));
}

function providerLabel(provider: string) {
  return providerOption(provider)?.shortLabel ?? provider;
}

function capabilityLabel(capability: string) {
  const labels: Record<string, string> = {
    text: '文本',
    vision: '多模态',
    MEDICAL_EXPERT_TEXT: '医疗文本',
    TOOL_CALLING_ORCHESTRATOR: '工具编排',
  };
  return labels[capability] ?? capability;
}

function capabilityValues(capability: string) {
  const values = capability
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean);
  return values.length ? values : [capability];
}

function capabilitiesFromValue(capability: string): Capability[] {
  const values = capabilityValues(capability).filter((value): value is Capability =>
    capabilityOptions.some((option) => option.value === value),
  );
  return values.length ? values : ['text'];
}

function capabilityLabels(capability: string) {
  return capabilityValues(capability).map(capabilityLabel);
}

function serializeCapabilities(capabilities: Capability[]) {
  return capabilityOptions
    .map((option) => option.value)
    .filter((value) => capabilities.includes(value))
    .join(',');
}

function modelSupportsCapability(model: ModelConfig, capability: Capability) {
  return capabilityValues(model.capability).includes(capability);
}

function defaultCapabilitiesForModel(provider: string, model: string): Capability[] {
  if (provider === 'openai_responses' && model === 'gpt-5.5') {
    return ['text', 'vision'];
  }
  if (provider === 'gemini') {
    return ['text', 'vision'];
  }
  if (provider === 'qwen' && (model === 'qwen3.7-plus' || model.includes('-vl-'))) {
    return ['text', 'vision'];
  }
  return providerOption(provider)?.defaultCapabilities ?? ['text'];
}
</script>

<template>
  <main class="app-shell">
    <header class="topbar">
      <div>
        <h1>test-benchmark</h1>
        <p>医疗模型评测工作台</p>
      </div>
      <div class="topbar-actions">
        <button v-if="authenticated" type="button" class="secondary" :disabled="loading" @click="logoutUser">
          退出登录
        </button>
        <div class="health-pill">API / PostgreSQL / Evaluation</div>
      </div>
    </header>

    <div v-if="notice" class="notice success">{{ notice }}</div>
    <div v-if="error" class="notice error">{{ error }}</div>

    <section v-if="authChecked && !authenticated" class="login-shell">
      <form class="login-panel" @submit.prevent="loginUser">
        <h2>登录评测平台</h2>
        <p>请输入服务端配置的访问密码。</p>
        <label>
          访问密码
          <input
            v-model="loginForm.password"
            type="password"
            autocomplete="current-password"
            required
            autofocus
          />
        </label>
        <button type="submit" :disabled="loading || !loginForm.password">
          {{ loading ? '登录中' : '登录' }}
        </button>
      </form>
    </section>

    <section v-else-if="!authChecked" class="section">
      <div class="empty">正在检查登录状态...</div>
    </section>

    <template v-else>
      <nav class="tabs" aria-label="primary">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        type="button"
        :class="{ active: activeTab === tab.id }"
        @click="activeTab = tab.id"
      >
        {{ tab.label }}
      </button>
      </nav>

    <section v-if="activeTab === 'models'" class="section">
      <div class="section-head">
        <div>
          <h2>模型配置</h2>
          <p>API key 仅保存在后端，页面只显示脱敏值。</p>
        </div>
        <button type="button" @click="openCreateModelDialog">新增模型</button>
      </div>

      <table>
        <thead>
          <tr>
            <th>名称</th>
            <th>模型服务商</th>
            <th>模型</th>
            <th>能力</th>
            <th>Key</th>
            <th>状态</th>
            <th>测试结果</th>
            <th>最近测试时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="model in models" :key="model.id">
            <td>{{ model.name }}</td>
            <td>
              <span class="provider-name">{{ providerLabel(model.provider) }}</span>
            </td>
            <td>{{ model.model }}</td>
            <td>
              <span
                v-for="capability in capabilityLabels(model.capability)"
                :key="capability"
                class="tag muted capability-tag"
              >
                {{ capability }}
              </span>
            </td>
            <td>{{ model.apiKeyMasked || '未配置' }}</td>
            <td>{{ model.enabled ? '启用' : '停用' }}</td>
            <td>
              <span class="tag" :class="modelTestStatusClass(model)">{{ formatModelTestStatus(model) }}</span>
              <small v-if="model.lastTestLatencyMs" class="cell-subtle">{{ model.lastTestLatencyMs }}ms</small>
              <small v-if="model.lastTestError" class="cell-error">{{ model.lastTestError }}</small>
            </td>
            <td>{{ formatDateTime(model.lastTestedAt) }}</td>
            <td>
              <div class="row-actions">
                <button type="button" class="secondary" @click="editModel(model)">编辑</button>
                <button type="button" class="secondary" :disabled="isModelTesting(model.id)" @click="testModel(model.id)">
                  {{ isModelTesting(model.id) ? '测试中' : '测试' }}
                </button>
              </div>
            </td>
          </tr>
          <tr v-if="!models.length">
            <td colspan="9" class="empty">暂无模型配置</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section v-if="activeTab === 'benchmarks'" class="section">
      <div class="section-head">
        <div>
          <h2>题集管理</h2>
        </div>
        <div>
          <input
            ref="benchmarkFileInput"
            class="file-input"
            type="file"
            accept=".jsonl,application/jsonl,text/plain"
            @change="importBenchmarkFile"
          />
          <button type="button" :disabled="loading" @click="openBenchmarkFilePicker">导入题集</button>
        </div>
      </div>

      <table>
        <thead>
          <tr>
            <th>题集</th>
            <th>类型</th>
            <th>模态</th>
            <th>题量</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="set in benchmarkSets" :key="set.id">
            <td>{{ set.name }}</td>
            <td>{{ set.category }}</td>
            <td>{{ set.modality }}</td>
            <td>{{ set.questionCount }}</td>
            <td><button type="button" class="secondary" @click="viewQuestions(set.id)">查看题目</button></td>
          </tr>
          <tr v-if="!benchmarkSets.length">
            <td colspan="5" class="empty">暂无题集，请先导入</td>
          </tr>
        </tbody>
      </table>

      <div v-if="questions.length" class="detail-list">
        <h3>题目预览</h3>
        <article v-for="question in questions" :key="question.id" class="question-row">
          <div class="question-meta">#{{ question.sourceRow }} · {{ question.questionType }}</div>
          <template v-if="editingQuestionId === question.id">
            <div class="question-edit-grid">
              <label>
                类型
                <select v-model="questionForm.questionType">
                  <option value="qa">问答题</option>
                  <option value="choice">选择题</option>
                </select>
              </label>
              <label class="wide-field">
                题目
                <textarea v-model="questionForm.question" rows="4" />
              </label>
              <label class="wide-field">
                选项
                <textarea v-model="questionForm.options" rows="4" />
              </label>
              <label class="wide-field">
                答案
                <textarea v-model="questionForm.answer" rows="4" />
              </label>
            </div>
            <div class="row-actions">
              <button type="button" :disabled="loading" @click="saveQuestion(question.id)">保存题目</button>
              <button type="button" class="secondary" :disabled="loading" @click="cancelQuestionEdit">取消</button>
            </div>
          </template>
          <template v-else>
            <p>{{ question.question }}</p>
            <pre v-if="question.options">{{ question.options }}</pre>
            <strong>答案：{{ question.answer }}</strong>
            <div class="row-actions question-actions">
              <button type="button" class="secondary" @click="editQuestion(question)">编辑</button>
              <button type="button" class="danger" @click="deleteQuestion(question.id)">删除</button>
            </div>
          </template>
        </article>
      </div>
    </section>

    <section v-if="activeTab === 'runs'" class="section">
      <div class="section-head">
        <div>
          <h2>评测运行</h2>
          <p>选择一个题集和一个或多个已启用模型后发起评测。</p>
        </div>
      </div>

      <div class="run-panel">
        <label>
          题集
          <select v-model.number="selectedBenchmarkSetId">
            <option v-for="set in benchmarkSets" :key="set.id" :value="set.id">
              {{ set.name }} · {{ set.questionCount }} 题
            </option>
          </select>
        </label>
        <div class="run-summary">
          可选模型：{{ runnableModels.length }} 个
        </div>
        <button type="button" :disabled="loading" @click="openRunDialog">启动评测</button>
      </div>

      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>题集</th>
            <th>状态</th>
            <th>进度</th>
            <th>准确率</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="run in runs" :key="run.id">
            <td>#{{ run.id }}</td>
            <td>{{ run.benchmarkSetName || run.benchmarkSetId }}</td>
            <td>{{ formatStatus(run.status) }}</td>
            <td>{{ run.completedCount }} / {{ run.totalCount }}</td>
            <td>{{ formatPercent(run.accuracy) }}</td>
            <td>
              <div class="row-actions">
                <button type="button" class="secondary" @click="openRunDetails(run.id)">查看明细</button>
                <button v-if="canStopRun(run)" type="button" class="danger" @click="stopRun(run.id)">结束</button>
              </div>
            </td>
          </tr>
          <tr v-if="!runs.length">
            <td colspan="6" class="empty">暂无评测运行</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section v-if="activeTab === 'results'" class="section">
      <div class="section-head">
        <div>
          <h2>结果看板</h2>
          <p>默认展示全部模型，并按最近一次评测记录汇总得分。</p>
        </div>
        <button type="button" class="secondary" :disabled="loading" @click="loadModelScores">刷新看板</button>
      </div>

      <div class="dashboard-summary">
        <div>
          <span>全部模型</span>
          <strong>{{ modelScores.length }}</strong>
        </div>
        <div>
          <span>已评测 / 应评测</span>
          <strong>{{ evaluatedModelScores.length }} / {{ modelScores.length }}</strong>
        </div>
        <div>
          <span>当前最高分</span>
          <strong>{{ bestModelScore ? `${bestModelScore.modelName} · ${formatPercent(bestModelScore.accuracy)}` : '-' }}</strong>
        </div>
        <div>
          <span>平均准确率</span>
          <strong>{{ scoredModelScores.length ? formatPercent(averageModelAccuracy) : '-' }}</strong>
        </div>
      </div>

      <div class="score-board">
        <article
          v-for="score in sortedModelScores"
          :key="score.modelConfigId"
          class="score-row"
          :class="{ 'score-row-empty': !score.latestRunId || !score.scoredCount }"
        >
          <div class="score-main">
            <div>
              <h3>{{ score.modelName }}</h3>
              <p>{{ providerLabel(score.provider) }} · {{ score.model }}</p>
            </div>
            <div class="score-result">
              <strong>{{ modelScoreStatus(score) }}</strong>
              <button
                type="button"
                class="secondary compact"
                :disabled="!score.latestRunId || loading"
                @click="score.latestRunId && openRunDetails(score.latestRunId)"
              >
                明细
              </button>
            </div>
          </div>
          <div class="score-bar" aria-hidden="true">
            <span :style="{ width: score.scoredCount ? modelScoreBarWidth(score) : '0%' }"></span>
          </div>
          <div class="score-meta">
            <span>题集：{{ score.benchmarkSetName || '-' }}</span>
            <span>运行：{{ score.latestRunId ? `#${score.latestRunId}` : '-' }}</span>
            <span>状态：{{ formatOptionalStatus(score.latestRunStatus) }}</span>
            <span>得分：{{ score.correctCount }} / {{ score.scoredCount || score.totalCount }}</span>
            <span>时间：{{ formatDateTime(score.latestEvaluatedAt) }}</span>
          </div>
        </article>
        <div v-if="!modelScores.length" class="empty dashboard-empty">
          暂无模型配置
        </div>
      </div>
    </section>

    <div v-if="detailRun" class="modal-backdrop" role="presentation" @click.self="closeRunDetails">
      <section class="modal-panel modal-panel-xl" role="dialog" aria-modal="true" aria-labelledby="run-detail-title">
        <div class="modal-head">
          <div>
            <h2 id="run-detail-title">评测明细 #{{ detailRun.id }}</h2>
            <p>{{ detailRun.benchmarkSetName || detailRun.benchmarkSetId }} · {{ formatStatus(detailRun.status) }}</p>
          </div>
          <button type="button" class="secondary" @click="closeRunDetails">关闭</button>
        </div>

        <div class="modal-detail">
          <div class="progress-panel progress-panel-compact">
            <div>
              <strong>{{ detailRun.completedCount }} / {{ detailRun.totalCount }}</strong>
              <span>准确率 {{ formatPercent(detailRun.accuracy) }}</span>
              <button
                v-if="canStopRun(detailRun)"
                type="button"
                class="danger"
                :disabled="loading"
                @click="stopRun(detailRun.id)"
              >
                结束评测
              </button>
            </div>
            <div class="progress-bar"><span :style="{ width: `${progressPercent(detailRun)}%` }"></span></div>
          </div>

          <div class="modal-table-scroll">
            <table class="results-table results-table-sticky">
              <thead>
                <tr>
                  <th>模型</th>
                  <th>题目</th>
                  <th>标准答案</th>
                  <th>提取答案</th>
                  <th>状态</th>
                  <th>结果</th>
                  <th>耗时</th>
                  <th>问答记录</th>
                </tr>
              </thead>
              <tbody>
                <template v-for="result in resultsForRun(detailRun.id)" :key="result.id">
                  <tr>
                    <td>{{ result.modelName || result.modelConfigId }}</td>
                    <td class="wide-cell">
                      <p>{{ result.question }}</p>
                    </td>
                    <td>{{ result.expectedAnswer }}</td>
                    <td>{{ result.extractedAnswer || '-' }}</td>
                    <td>
                      <span :class="statusBadgeClass(result.status)">{{ formatStatus(result.status) }}</span>
                    </td>
                    <td>
                      <span v-if="result.isCorrect === true" class="tag ok">正确</span>
                      <span v-else-if="result.isCorrect === false" class="tag bad">错误</span>
                      <span v-else class="tag muted">待复核</span>
                    </td>
                    <td>{{ result.latencyMs ? `${result.latencyMs}ms` : '-' }}</td>
                    <td>
                      <button type="button" class="secondary" @click="toggleResultRecord(result.id)">
                        {{ expandedResultId === result.id ? '收起记录' : '查看记录' }}
                      </button>
                    </td>
                  </tr>
                  <tr v-if="expandedResultId === result.id" class="record-row">
                    <td colspan="8">
                      <div class="record-panel">
                        <section>
                          <h3>发送给模型的内容</h3>
                          <pre>{{ result.prompt }}</pre>
                        </section>
                        <section>
                          <h3>AI 回复</h3>
                          <pre>{{ result.modelAnswer || '暂无回复' }}</pre>
                        </section>
                        <section v-if="result.errorMessage">
                          <h3>错误信息</h3>
                          <pre>{{ result.errorMessage }}</pre>
                        </section>
                        <section class="record-grid">
                          <div>
                            <span>标准答案</span>
                            <strong>{{ result.expectedAnswer }}</strong>
                          </div>
                          <div>
                            <span>提取答案</span>
                            <strong>{{ result.extractedAnswer || '-' }}</strong>
                          </div>
                          <div>
                            <span>题目类型</span>
                            <strong>{{ result.questionType || '-' }}</strong>
                          </div>
                        </section>
                      </div>
                    </td>
                  </tr>
                </template>
                <tr v-if="!resultsForRun(detailRun.id).length">
                  <td colspan="8" class="empty">暂无明细</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </div>

    <div v-if="modelDialogOpen" class="modal-backdrop" role="presentation" @click.self="closeModelDialog">
      <section class="modal-panel modal-panel-wide" role="dialog" aria-modal="true" aria-labelledby="model-dialog-title">
        <div class="modal-head">
          <div>
            <h2 id="model-dialog-title">{{ modelDialogTitle }}</h2>
            <p>{{ isEditingModel ? 'API Key 留空会保留原 Key。' : '配置模型服务商、模型名称和调用参数。' }}</p>
          </div>
          <button type="button" class="secondary" @click="closeModelDialog">关闭</button>
        </div>

        <form class="modal-form form-grid" @submit.prevent="saveModel">
          <label>
            名称
            <input v-model="modelForm.name" required placeholder="deepseek-v4-pro" />
          </label>
          <label>
            模型服务商
            <select v-model="modelForm.provider" @change="applyProviderPreset">
              <option v-for="provider in providerOptions" :key="provider.value" :value="provider.value">
                {{ provider.label }}
              </option>
            </select>
          </label>
          <label>
            模型
            <select v-model="modelForm.model" required @change="applyModelPreset">
              <option v-for="model in modelOptionsForForm" :key="model" :value="model">
                {{ model }}
              </option>
            </select>
          </label>
          <label>
            Base URL
            <input v-model="modelForm.baseUrl" placeholder="https://api.example.com/v1" />
          </label>
          <label>
            API Key
            <input
              v-model="modelForm.apiKey"
              type="password"
              autocomplete="off"
              :placeholder="isEditingModel ? '留空则保留原 Key' : ''"
            />
          </label>
          <label v-if="isEditingModel" class="checkbox-row">
            <input v-model="modelForm.clearApiKey" type="checkbox" />
            清除 Key
          </label>
          <div class="field-group">
            能力
            <div class="capability-checks">
              <label v-for="capability in capabilityOptions" :key="capability.value" class="checkbox-row">
                <input
                  type="checkbox"
                  :checked="modelForm.capabilities.includes(capability.value)"
                  @change="toggleCapability(capability.value, $event)"
                />
                {{ capability.label }}
              </label>
            </div>
          </div>
          <label>
            Max Output Tokens
            <input v-model.number="modelForm.maxOutputTokens" type="number" min="128" max="32768" />
          </label>
          <label class="checkbox-row">
            <input v-model="modelForm.enabled" type="checkbox" />
            启用
          </label>
        </form>

        <div class="modal-actions">
          <button type="button" class="secondary" :disabled="loading" @click="closeModelDialog">取消</button>
          <button type="button" :disabled="loading" @click="saveModel">
            {{ isEditingModel ? '更新模型' : '保存模型' }}
          </button>
        </div>
      </section>
    </div>

    <div v-if="runDialogOpen" class="modal-backdrop" role="presentation" @click.self="closeRunDialog">
      <section class="modal-panel" role="dialog" aria-modal="true" aria-labelledby="run-dialog-title">
        <div class="modal-head">
          <div>
            <h2 id="run-dialog-title">选择评测模型</h2>
            <p>为当前题集选择一个或多个支持文本能力的模型。</p>
          </div>
          <button type="button" class="secondary" @click="closeRunDialog">关闭</button>
        </div>

        <div class="modal-list">
          <label v-for="model in runnableModels" :key="model.id" class="modal-model-row">
            <input
              type="checkbox"
              :checked="selectedModelIds.includes(model.id)"
              @change="onModelSelectionChange(model.id, $event)"
            />
            <span>
              <strong>{{ model.name }}</strong>
              <small>{{ providerLabel(model.provider) }} · {{ model.model }}</small>
            </span>
          </label>
        </div>

        <div class="modal-actions">
          <button type="button" class="secondary" @click="closeRunDialog">取消</button>
          <button type="button" :disabled="loading || !selectedModelIds.length" @click="createRun">
            确认启动
          </button>
        </div>
      </section>
    </div>
    </template>
  </main>
</template>
