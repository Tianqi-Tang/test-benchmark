<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue';
import Button from 'primevue/button';
import Card from 'primevue/card';
import Checkbox from 'primevue/checkbox';
import Column from 'primevue/column';
import ConfirmDialog from 'primevue/confirmdialog';
import DataTable from 'primevue/datatable';
import Dialog from 'primevue/dialog';
import InputNumber from 'primevue/inputnumber';
import InputText from 'primevue/inputtext';
import Panel from 'primevue/panel';
import Password from 'primevue/password';
import Popover from 'primevue/popover';
import ProgressBar from 'primevue/progressbar';
import Select from 'primevue/select';
import TabMenu from 'primevue/tabmenu';
import Tag from 'primevue/tag';
import Toast from 'primevue/toast';
import Tooltip from 'primevue/tooltip';
import { useConfirm } from 'primevue/useconfirm';
import { useToast } from 'primevue/usetoast';

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
  lastTestRawResponse: unknown | null;
  lastTestedAt: string | null;
};

type BenchmarkSet = {
  id: number;
  name: string;
  category: string;
  sourcePath: string | null;
  modality: string;
  questionCount: number;
  requiresJudge: boolean;
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
  modelNames: string[];
  judgeModelName: string | null;
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
  evaluationRunId: number;
  modelConfigId: number;
  modelName: string | null;
  benchmarkQuestionId: number;
  questionSourceRow: number | null;
  question: string | null;
  options: string | null;
  questionType: string | null;
  status: string;
  prompt: string;
  expectedAnswer: string;
  maxScore: number;
  modelAnswer: string | null;
  rawResponse: Record<string, unknown> | null;
  extractedAnswer: string | null;
  isCorrect: boolean | null;
  score: number | null;
  judgeModelConfigId: number | null;
  judgeModelName: string | null;
  judgeStatus: string | null;
  judgeScoreRatio: number | null;
  judgeReason: string | null;
  judgePrompt: string | null;
  judgeRawResponse: Record<string, unknown> | null;
  latencyMs: number | null;
  errorMessage: string | null;
};

type JsonRecordDialog = {
  title: string;
  payload: unknown;
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
  completedCount: number;
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
  defaultMaxOutputTokens?: number;
};

type CapabilityOption = {
  value: Capability;
  label: string;
};

type ModelTestState = {
  status: 'success' | 'failed';
  message: string | null;
  latencyMs: number | null;
  rawResponse?: unknown;
};

type TabChangeEvent = {
  index: number;
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
const selectedJudgeModelIds = ref<Record<number, number | null>>({});
const editingModelId = ref<number | null>(null);
const editingBenchmarkSetId = ref<number | null>(null);
const editingQuestionId = ref<number | null>(null);
const benchmarkFileInput = ref<HTMLInputElement | null>(null);
const modelDialogOpen = ref(false);
const benchmarkSetDialogOpen = ref(false);
const runDialogOpen = ref(false);
const runCreateLoading = ref(false);
const benchmarkSetFormElement = ref<HTMLFormElement | null>(null);
const modelFormElement = ref<HTMLFormElement | null>(null);
const detailRunId = ref<number | null>(null);
const detailResultsLoading = ref(false);
const detailResultsRequestId = ref(0);
const selectedResultRecord = ref<EvaluationResult | null>(null);
const jsonRecordDialog = ref<JsonRecordDialog | null>(null);
const questionPopover = ref<InstanceType<typeof Popover> | null>(null);
const questionPopoverResult = ref<EvaluationResult | null>(null);
const retryingResultIds = ref<Set<number>>(new Set());
const testingModelIds = ref<Set<number>>(new Set());
const modelTestStates = ref<Record<number, ModelTestState>>({});
const selectedModelTestRecord = ref<{ modelName: string; payload: unknown } | null>(null);
const authChecked = ref(false);
const authenticated = ref(false);
const loading = ref(false);
const notice = ref('');
const error = ref('');
const confirm = useConfirm();
const toast = useToast();
const vTooltip = Tooltip;
const maxOutputTokensLimit = 1048576;

const tabMenuItems = computed(() => tabs.map((tab) => ({ label: tab.label })));
const activeTabIndex = computed(() => {
  const index = tabs.findIndex((tab) => tab.id === activeTab.value);
  return index >= 0 ? index : 0;
});
const detailDialogOpen = computed({
  get: () => detailRunId.value !== null,
  set: (visible: boolean) => {
    if (!visible) {
      closeRunDetails();
    }
  },
});

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

const benchmarkSetForm = reactive({
  name: '',
  category: '',
  modality: '',
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
    label: '阿里云百炼',
    shortLabel: '阿里云',
    defaultModel: 'qwen3.7-plus',
    modelOptions: [
      'qwen3.7-plus',
      'deepseek-v4-pro',
      'deepseek-v4-flash',
      'glm-5.1',
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
    value: 'nvidia',
    label: 'NVIDIA NIM',
    shortLabel: 'NVIDIA',
    defaultModel: 'deepseek-v4-pro',
    modelOptions: ['deepseek-v4-pro', 'deepseek-v4-flash'],
    baseUrl: 'https://integrate.api.nvidia.com/v1',
    defaultCapabilities: ['text'],
    defaultMaxOutputTokens: 16384,
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
    shortLabel: 'Google Gemini',
    defaultModel: 'gemini-3.5-flash',
    modelOptions: ['gemini-3.5-flash', 'gemini-3.5-pro', 'gemini-2.0-flash'],
    baseUrl: 'https://generativelanguage.googleapis.com',
    defaultCapabilities: ['text', 'vision'],
  },
  {
    value: 'openrouter',
    label: 'OpenRouter',
    shortLabel: 'OpenRouter',
    defaultModel: 'anthropic/claude-fable-5',
    modelOptions: ['anthropic/claude-fable-5', 'qwen/qwen3.7-plus', 'google/gemini-3.5-flash'],
    baseUrl: 'https://openrouter.ai/api/v1',
    defaultCapabilities: ['text'],
    defaultMaxOutputTokens: 128000,
  },
];

const modelPresetNames = new Set(providerOptions.flatMap((provider) => provider.modelOptions));

let pollTimer: number | undefined;
const appBasePath = import.meta.env.BASE_URL ?? '/';

const hasActiveRuns = computed(() => runs.value.some((run) => run.status === 'pending' || run.status === 'running'));
const runnableModels = computed(() => models.value.filter((model) => model.enabled && modelSupportsCapability(model, 'text')));
const judgeModels = computed(() =>
  runnableModels.value.filter((model) => model.lastTestStatus === 'success' || modelTestStates.value[model.id]?.status === 'success'),
);
const isEditingModel = computed(() => editingModelId.value !== null);
const selectedProvider = computed(() => providerOption(modelForm.provider) ?? providerOptions[0]);
const modelOptionsForForm = computed(() => {
  const options = selectedProvider.value.modelOptions;
  return modelForm.model && !options.includes(modelForm.model) ? [modelForm.model, ...options] : options;
});
const modelDialogTitle = computed(() => (isEditingModel.value ? '编辑模型' : '新增模型'));
const selectedBenchmarkSet = computed(() => {
  return benchmarkSets.value.find((set) => set.id === selectedBenchmarkSetId.value) ?? null;
});
const selectedBenchmarkRequiresJudge = computed(() => selectedBenchmarkSet.value?.requiresJudge ?? false);
const selectedModelsMissingJudge = computed(() => {
  if (!selectedBenchmarkRequiresJudge.value) return [];
  return selectedModelIds.value.filter((modelId) => {
    const judgeModelId = selectedJudgeModelIds.value[modelId] ?? null;
    return !judgeModelId || !judgeModelOptionsFor(modelId).some((model) => model.id === judgeModelId);
  });
});
const canSubmitRun = computed(() => {
  return !runCreateLoading.value && Boolean(selectedModelIds.value.length) && selectedModelsMissingJudge.value.length === 0;
});
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

function confirmLogout(event: Event) {
  confirm.require({
    target: event.currentTarget as HTMLElement,
    message: '确定退出当前评测平台会话吗？',
    header: '退出登录',
    icon: 'pi pi-sign-out',
    rejectLabel: '取消',
    acceptLabel: '退出',
    acceptClass: 'p-button-danger',
    accept: () => {
      void logoutUser();
    },
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
  modelTestStates.value = {};
  detailRunId.value = null;
  detailResultsLoading.value = false;
  selectedResultRecord.value = null;
  retryingResultIds.value = new Set();
  modelDialogOpen.value = false;
  benchmarkSetDialogOpen.value = false;
  runDialogOpen.value = false;
  runCreateLoading.value = false;
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
      if (selectedResultRecord.value) {
        selectedResultRecord.value = runResults.value[detailRunId.value]?.find((row) => row.id === selectedResultRecord.value?.id) ?? null;
      }
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
  if (selectedBenchmarkSetId.value && !benchmarkSets.value.some((set) => set.id === selectedBenchmarkSetId.value)) {
    selectedBenchmarkSetId.value = null;
    questions.value = [];
  }
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
  modelForm.maxOutputTokens = defaultMaxOutputTokensForModel(preset.value, preset.defaultModel);
  if (!modelForm.name || modelPresetNames.has(modelForm.name)) {
    modelForm.name = preset.defaultModel;
  }
}

function applyModelPreset() {
  modelForm.capabilities = defaultCapabilitiesForModel(modelForm.provider, modelForm.model);
  modelForm.maxOutputTokens = defaultMaxOutputTokensForModel(modelForm.provider, modelForm.model);
  if (!modelForm.name || modelPresetNames.has(modelForm.name)) {
    modelForm.name = modelForm.model;
  }
}

function openCreateModelDialog() {
  resetModelForm();
  applyProviderPreset();
  modelDialogOpen.value = true;
}

function closeModelDialog() {
  modelDialogOpen.value = false;
  resetModelForm();
}

async function saveModel() {
  const name = modelForm.name.trim();
  const provider = normalizeProviderValue(modelForm.provider).trim();
  const model = modelForm.model.trim();
  const baseUrl = modelForm.baseUrl.trim();
  const apiKey = modelForm.apiKey.trim();

  if (!name) {
    error.value = '请填写模型名称';
    return;
  }
  if (!provider) {
    error.value = '请选择模型服务商';
    return;
  }
  if (!model) {
    error.value = '请选择模型';
    return;
  }
  if (!modelForm.capabilities.length) {
    error.value = '请至少选择一种模型能力';
    return;
  }
  await withLoading(async () => {
    const payload = {
      name,
      provider,
      model,
      baseUrl: baseUrl || null,
      apiKey: apiKey || undefined,
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
          apiKey: apiKey || null,
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
  const startedAt = performance.now();
  const modelName = modelNameById(modelId);
  try {
    const result = await api<{ ok: boolean; message: string; responseText?: string; rawResponse?: unknown }>(`/api/models/${modelId}/test`, {
      method: 'POST',
    });
    if (result.ok) {
      const message = result.responseText?.trim() || '调用成功';
      modelTestStates.value = {
        ...modelTestStates.value,
        [modelId]: { status: 'success', message, latencyMs: Math.round(performance.now() - startedAt), rawResponse: result.rawResponse },
      };
      toast.add({ severity: 'success', summary: '模型测试成功', detail: `${modelName}：${message}`, life: 4000 });
    } else {
      modelTestStates.value = {
        ...modelTestStates.value,
        [modelId]: { status: 'failed', message: result.message, latencyMs: Math.round(performance.now() - startedAt), rawResponse: result.rawResponse },
      };
      toast.add({ severity: 'error', summary: '模型测试失败', detail: `${modelName}：${result.message}`, life: 7000 });
    }
    await loadModels();
    syncJudgeSelections();
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    modelTestStates.value = {
      ...modelTestStates.value,
      [modelId]: { status: 'failed', message, latencyMs: Math.round(performance.now() - startedAt) },
    };
    toast.add({ severity: 'error', summary: '模型测试失败', detail: `${modelName}：${message}`, life: 7000 });
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

function editBenchmarkSet(set: BenchmarkSet) {
  editingBenchmarkSetId.value = set.id;
  benchmarkSetForm.name = set.name;
  benchmarkSetForm.category = set.category;
  benchmarkSetForm.modality = set.modality;
  benchmarkSetDialogOpen.value = true;
}

function closeBenchmarkSetDialog() {
  benchmarkSetDialogOpen.value = false;
  editingBenchmarkSetId.value = null;
  benchmarkSetForm.name = '';
  benchmarkSetForm.category = '';
  benchmarkSetForm.modality = '';
}

async function saveBenchmarkSet() {
  if (!editingBenchmarkSetId.value) return;
  await withLoading(async () => {
    const updated = await api<BenchmarkSet>(`/api/benchmark-sets/${editingBenchmarkSetId.value}`, {
      method: 'PUT',
      body: JSON.stringify({
        name: benchmarkSetForm.name,
      }),
    });
    notice.value = '题集名称已更新';
    closeBenchmarkSetDialog();
    await Promise.all([loadBenchmarkSets(), loadRuns(), loadModelScores()]);
    if (selectedBenchmarkSetId.value === updated.id) {
      await loadQuestions(updated.id);
    }
  });
}

function confirmDeleteBenchmarkSet(set: BenchmarkSet, event: Event) {
  confirm.require({
    target: event.currentTarget as HTMLElement,
    message: `确定删除题集“${set.name}”吗？该题集下的题目、评测运行和结果记录都会删除。`,
    header: '删除题集',
    icon: 'pi pi-exclamation-triangle',
    rejectLabel: '取消',
    acceptLabel: '删除',
    acceptClass: 'p-button-danger',
    accept: () => {
      void deleteBenchmarkSet(set);
    },
  });
}

async function deleteBenchmarkSet(set: BenchmarkSet) {
  await withLoading(async () => {
    await api<void>(`/api/benchmark-sets/${set.id}`, { method: 'DELETE' });
    notice.value = '题集已删除';
    if (selectedBenchmarkSetId.value === set.id) {
      selectedBenchmarkSetId.value = null;
      questions.value = [];
    }
    detailRunId.value = null;
    selectedResultRecord.value = null;
    await Promise.all([loadBenchmarkSets(), loadRuns(), loadModelScores()]);
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

function openRunDialog() {
  if (!runnableModels.value.length) {
    error.value = '请先配置至少一个支持文本能力的已启用模型';
    return;
  }
  selectedModelIds.value = [];
  selectedJudgeModelIds.value = {};
  error.value = '';
  notice.value = '';
  runDialogOpen.value = true;
}

function closeRunDialog() {
  if (runCreateLoading.value) return;
  runDialogOpen.value = false;
}

function confirmDeleteRun(run: EvaluationRun, event: Event) {
  confirm.require({
    target: event.currentTarget as HTMLElement,
    message: `确定删除评测 #${run.id} 吗？该评测的逐题结果也会一起删除。`,
    header: '删除评测',
    icon: 'pi pi-exclamation-triangle',
    rejectLabel: '取消',
    acceptLabel: '删除',
    acceptClass: 'p-button-danger',
    accept: () => {
      void deleteRun(run);
    },
  });
}

function confirmStopRun(run: EvaluationRun, event: Event) {
  confirm.require({
    target: event.currentTarget as HTMLElement,
    message: `确定结束评测 #${run.id} 吗？已经完成的结果会保留，未完成的题目将停止评测。`,
    header: '结束评测',
    icon: 'pi pi-exclamation-triangle',
    rejectLabel: '取消',
    acceptLabel: '结束评测',
    acceptClass: 'p-button-warning',
    accept: () => {
      void stopRun(run.id);
    },
  });
}

async function deleteRun(run: EvaluationRun) {
  await withLoading(async () => {
    await api<void>(`/api/evaluation-runs/${run.id}`, { method: 'DELETE' });
    toast.add({
      severity: 'success',
      summary: '评测已删除',
      detail: `#${run.id} · ${run.benchmarkSetName || benchmarkSetNameById(run.benchmarkSetId)}`,
      life: 5000,
    });
    if (detailRunId.value === run.id) {
      closeRunDetails();
    }
    await Promise.all([loadRuns(), loadModelScores()]);
  });
}

async function createRun() {
  if (!selectedBenchmarkSetId.value) {
    toast.add({ severity: 'warn', summary: '请选择题集', detail: '启动评测前需要先选择一个题集。', life: 4000 });
    return;
  }
  if (!selectedModelIds.value.length) {
    toast.add({ severity: 'warn', summary: '请选择模型', detail: '启动评测前需要至少选择一个模型。', life: 4000 });
    return;
  }
  if (selectedBenchmarkRequiresJudge.value) {
    syncJudgeSelections();
    if (selectedModelsMissingJudge.value.length) {
      const missingNames = selectedModelsMissingJudge.value.map(modelNameById).join('、');
      toast.add({
        severity: 'warn',
        summary: '请选择 Judge 模型',
        detail: `${missingNames} 需要选择最近一次测试通过且不同于自身的 Judge 模型。`,
        life: 6000,
      });
      return;
    }
  }
  runCreateLoading.value = true;
  error.value = '';
  notice.value = '';
  const benchmarkName = benchmarkSetNameById(selectedBenchmarkSetId.value);
  const selectedModelNames = selectedModelIds.value.map(modelNameById).join('、');
  const judgeModelConfigIds = Object.fromEntries(
    selectedModelIds.value.map((modelId) => [modelId, selectedJudgeModelIds.value[modelId]]),
  );
  try {
    const createdRuns = await api<EvaluationRun[]>('/api/evaluation-runs', {
      method: 'POST',
      body: JSON.stringify({
        benchmarkSetId: selectedBenchmarkSetId.value,
        modelConfigIds: selectedModelIds.value,
        judgeModelConfigIds: selectedBenchmarkRequiresJudge.value ? judgeModelConfigIds : {},
      }),
    });
    const firstRun = createdRuns[0];
    if (!firstRun) {
      throw new Error('评测任务创建失败');
    }
    const requestId = detailResultsRequestId.value + 1;
    detailResultsRequestId.value = requestId;
    detailRunId.value = firstRun.id;
    detailResultsLoading.value = true;
    selectedResultRecord.value = null;
    activeTab.value = 'runs';
    runDialogOpen.value = false;
    toast.add({
      severity: 'success',
      summary: '评测已启动',
      detail: `${createdRuns.map((run) => `#${run.id}`).join('、')} · ${benchmarkName} · ${selectedModelNames}`,
      life: 5000,
    });
    await loadRuns();
    window.setTimeout(() => {
      void loadRunDetailsInBackground(firstRun.id, requestId);
    }, 0);
    void loadModelScores();
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    toast.add({ severity: 'error', summary: '启动评测失败', detail: `${benchmarkName}：${message}`, life: 7000 });
    if (detailRunId.value === null) {
      runDialogOpen.value = true;
    }
  } finally {
    runCreateLoading.value = false;
  }
}

function openRunDetails(runId: number) {
  const requestId = detailResultsRequestId.value + 1;
  detailResultsRequestId.value = requestId;
  detailRunId.value = runId;
  selectedResultRecord.value = null;
  detailResultsLoading.value = true;
  error.value = '';
  window.setTimeout(() => {
    void loadRunDetailsInBackground(runId, requestId);
  }, 0);
}

async function loadRunDetailsInBackground(runId: number, requestId: number) {
  try {
    await loadRunResults(runId);
  } catch (err) {
    if (detailResultsRequestId.value === requestId && detailRunId.value === runId) {
      error.value = err instanceof Error ? err.message : String(err);
    }
  } finally {
    if (detailResultsRequestId.value === requestId && detailRunId.value === runId) {
      detailResultsLoading.value = false;
    }
  }
}

function closeRunDetails() {
  detailResultsRequestId.value += 1;
  detailRunId.value = null;
  detailResultsLoading.value = false;
  selectedResultRecord.value = null;
  retryingResultIds.value = new Set();
}

async function stopRun(runId: number) {
  await withLoading(async () => {
    const run = await api<EvaluationRun>(`/api/evaluation-runs/${runId}/stop`, { method: 'POST' });
    toast.add({
      severity: 'success',
      summary: '评测已结束',
      detail: `#${run.id} · ${run.benchmarkSetName || benchmarkSetNameById(run.benchmarkSetId)}`,
      life: 5000,
    });
    await loadRuns();
    await loadModelScores();
    if (detailRunId.value === run.id) {
      await loadRunResults(run.id);
    }
  });
}

function openResultRecord(result: EvaluationResult) {
  selectedResultRecord.value = result;
}

function closeResultRecord() {
  selectedResultRecord.value = null;
}

function openJsonRecordDialog(title: string, payload: unknown) {
  jsonRecordDialog.value = { title, payload };
}

function closeJsonRecordDialog() {
  jsonRecordDialog.value = null;
}

function openModelTestRecord(model: ModelConfig) {
  selectedModelTestRecord.value = {
    modelName: model.name,
    payload: modelTestStates.value[model.id]?.rawResponse ?? model.lastTestRawResponse ?? {
      status: model.lastTestStatus,
      error: model.lastTestError,
      latencyMs: model.lastTestLatencyMs,
      testedAt: model.lastTestedAt,
    },
  };
}

function closeModelTestRecord() {
  selectedModelTestRecord.value = null;
}

function formatJson(value: unknown) {
  return JSON.stringify(value ?? null, null, 2);
}

function modelRequestPayload(result: EvaluationResult) {
  return {
    prompt: result.prompt,
    raw_response: result.rawResponse,
  };
}

function judgeRequestPayload(result: EvaluationResult) {
  return {
    prompt: result.judgePrompt,
    raw_response: result.judgeRawResponse,
  };
}

function showQuestionPopover(event: Event, result: EvaluationResult) {
  questionPopoverResult.value = result;
  questionPopover.value?.toggle(event);
}

function canRetryResult(result: EvaluationResult) {
  if (retryingResultIds.value.has(result.id)) return false;
  if (result.status === 'judge_failed') return true;
  if (result.status === 'failed') return true;
  return result.status === 'completed' && result.modelAnswer !== null && !(result.extractedAnswer ?? '').trim();
}

function isRetryingResult(resultId: number) {
  return retryingResultIds.value.has(resultId);
}

async function retryResult(result: EvaluationResult) {
  if (!canRetryResult(result)) return;
  retryingResultIds.value = new Set([...retryingResultIds.value, result.id]);
  try {
    const updated = await api<EvaluationResult>(`/api/evaluation-results/${result.id}/retry`, { method: 'POST' });
    const rows = runResults.value[updated.evaluationRunId] ?? [];
    runResults.value = {
      ...runResults.value,
      [updated.evaluationRunId]: rows.map((row) => (row.id === updated.id ? updated : row)),
    };
    toast.add({
      severity: ['failed', 'judge_failed'].includes(updated.status) ? 'error' : 'success',
      summary: ['failed', 'judge_failed'].includes(updated.status) ? '重试失败' : '重试完成',
      detail: `${updated.modelName || `模型 #${updated.modelConfigId}`} · 结果 #${updated.id}`,
      life: 5000,
    });
    await Promise.all([loadRuns(), loadModelScores()]);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    toast.add({ severity: 'error', summary: '重试失败', detail: message, life: 7000 });
  } finally {
    const next = new Set(retryingResultIds.value);
    next.delete(result.id);
    retryingResultIds.value = next;
  }
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

function formatScore(value: number) {
  return (value * 100).toFixed(2);
}

function progressPercent(run: EvaluationRun) {
  if (run.totalCount === 0) return 0;
  return Math.round((run.completedCount / run.totalCount) * 100);
}

function resultsForRun(runId: number) {
  return runResults.value[runId] ?? [];
}

function modelNameById(modelId: number) {
  return models.value.find((model) => model.id === modelId)?.name ?? `模型 #${modelId}`;
}

function modelProviderTextById(modelId: number | null) {
  if (!modelId) return '';
  const model = models.value.find((item) => item.id === modelId);
  return model ? providerLabel(model.provider) : '';
}

function benchmarkSetNameById(setId: number | null) {
  if (!setId) return '未选择题集';
  return benchmarkSets.value.find((set) => set.id === setId)?.name ?? `题集 #${setId}`;
}

function judgeModelOptionsFor(modelId: number) {
  return judgeModels.value.filter((model) => model.id !== modelId);
}

function defaultJudgeModelIdFor(modelId: number) {
  const options = judgeModelOptionsFor(modelId);
  return (
    options.find((model) => model.provider === 'ant_ling' && model.model === 'AntAngelMed')?.id
    ?? options.find((model) => model.provider === 'ant_ling')?.id
    ?? options.find((model) => model.provider === 'deepseek')?.id
    ?? options[0]?.id
    ?? null
  );
}

function syncJudgeSelections() {
  const next: Record<number, number | null> = {};
  for (const modelId of selectedModelIds.value) {
    const current = selectedJudgeModelIds.value[modelId] ?? null;
    const options = judgeModelOptionsFor(modelId);
    next[modelId] = current && options.some((model) => model.id === current) ? current : defaultJudgeModelIdFor(modelId);
  }
  selectedJudgeModelIds.value = next;
}

function toggleRunModel(modelId: number) {
  const next = selectedModelIds.value.includes(modelId)
    ? selectedModelIds.value.filter((id) => id !== modelId)
    : [...selectedModelIds.value, modelId];
  selectedModelIds.value = next;
  syncJudgeSelections();
}

function selectedJudgeModelId(modelId: number) {
  return selectedJudgeModelIds.value[modelId] ?? null;
}

function setSelectedJudgeModelId(modelId: number, judgeModelId: number | null) {
  selectedJudgeModelIds.value = {
    ...selectedJudgeModelIds.value,
    [modelId]: judgeModelId,
  };
}

function isModelTestSuccessful(model: ModelConfig) {
  return (modelTestStates.value[model.id]?.status ?? model.lastTestStatus) === 'success';
}

function modelTestTooltip(model: ModelConfig) {
  return isModelTestSuccessful(model) ? '模型测试通过' : '模型测试未通过';
}

function modelScoreStatus(score: ModelScore) {
  if (!score.latestRunId) return '未评测';
  if (!score.scoredCount) return '无可评分结果';
  return formatScore(score.accuracy);
}

function modelScoreProgressValue(score: ModelScore) {
  if (!score.totalCount) return 0;
  return Math.round((score.completedCount / score.totalCount) * 100);
}

function modelScoreTagSeverity(score: ModelScore) {
  if (!score.latestRunId) return 'secondary';
  if (score.latestRunStatus === 'failed') return 'danger';
  if (score.latestRunStatus === 'running' || score.latestRunStatus === 'pending') return 'info';
  if (score.latestRunStatus === 'stopped') return 'warn';
  return score.scoredCount ? 'success' : 'secondary';
}

function runStatusTagSeverity(status: string) {
  if (status === 'failed') return 'danger';
  if (status === 'judge_failed') return 'warn';
  if (status === 'running' || status === 'pending') return 'info';
  if (status === 'stopped') return 'warn';
  if (status === 'completed') return 'success';
  return 'secondary';
}

function formatStatus(value: string) {
  const labels: Record<string, string> = {
    pending: '等待中',
    running: '运行中',
    completed: '完成',
    failed: '失败',
    judge_failed: '评分失败',
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

function formatJudgeStatus(value: string | null) {
  if (!value) return '-';
  const labels: Record<string, string> = {
    completed: '评分完成',
    failed: '评分失败',
  };
  return labels[value] ?? value;
}

function formatQuestionPreview(result: EvaluationResult | null) {
  if (!result) return '暂无题目';
  return [result.question, result.options].filter((value) => value && value.trim()).join('\n\n');
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
  if (isModelTesting(model.id)) return '测试中';
  const state = modelTestStates.value[model.id];
  const status = state?.status ?? model.lastTestStatus;
  if (!status) return '未测试';
  return status === 'success' ? '通过' : '失败';
}

function modelTestStatusClass(model: ModelConfig) {
  if (isModelTesting(model.id)) return 'muted';
  const state = modelTestStates.value[model.id];
  const status = state?.status ?? model.lastTestStatus;
  if (status === 'success') return 'ok';
  if (status === 'failed') return 'bad';
  return 'muted';
}

function modelTestLatency(model: ModelConfig) {
  return modelTestStates.value[model.id]?.latencyMs ?? model.lastTestLatencyMs;
}

function modelTestError(model: ModelConfig) {
  const state = modelTestStates.value[model.id];
  if (state?.status === 'failed') return state.message;
  return model.lastTestError;
}

function hasModelTestRecord(model: ModelConfig) {
  return Boolean(modelTestStates.value[model.id]?.rawResponse || model.lastTestRawResponse || model.lastTestStatus || model.lastTestError);
}

function isModelTesting(modelId: number) {
  return testingModelIds.value.has(modelId);
}

function canStopRun(run: EvaluationRun) {
  return run.status === 'pending' || run.status === 'running';
}

function canDeleteRun(run: EvaluationRun) {
  return ['completed', 'failed', 'stopped'].includes(run.status);
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

function questionTypeLabel(questionType: string | null) {
  const labels: Record<string, string> = {
    qa: '问答题',
    choice: '选择题',
  };
  return questionType ? labels[questionType] ?? questionType : '-';
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
  if (provider === 'openrouter' && model === 'google/gemini-3.5-flash') {
    return ['text', 'vision'];
  }
  if (provider === 'openrouter' && model === 'qwen/qwen3.7-plus') {
    return ['text', 'vision'];
  }
  if (provider === 'openrouter' && model === 'anthropic/claude-fable-5') {
    return ['text'];
  }
  if (provider === 'qwen' && (model === 'qwen3.7-plus' || model.includes('-vl-'))) {
    return ['text', 'vision'];
  }
  return providerOption(provider)?.defaultCapabilities ?? ['text'];
}

function defaultMaxOutputTokensForModel(provider: string, model: string) {
  if (provider === 'openrouter' && model === 'anthropic/claude-fable-5') {
    return 128000;
  }
  if (provider === 'openrouter' && (model === 'google/gemini-3.5-flash' || model === 'qwen/qwen3.7-plus')) {
    return 65536;
  }
  return providerOption(provider)?.defaultMaxOutputTokens ?? 2048;
}

function onTabChange(event: TabChangeEvent) {
  const tab = tabs[event.index];
  if (tab) {
    activeTab.value = tab.id;
  }
}
</script>

<template>
  <ConfirmDialog />
  <Toast position="top-right" />
  <main class="app-shell">
    <header class="topbar">
      <div class="brand-block">
        <h1>test-benchmark</h1>
        <p>医疗模型评测工作台</p>
      </div>
      <TabMenu
        v-if="authenticated"
        :model="tabMenuItems"
        :active-index="activeTabIndex"
        class="topbar-tabs"
        aria-label="primary"
        @tab-change="onTabChange"
      />
      <div class="topbar-actions">
        <Button
          v-if="authenticated"
          icon="pi pi-sign-out"
          text
          rounded
          severity="secondary"
          class="logout-button"
          :disabled="loading"
          title="退出登录"
          aria-label="退出登录"
          @click="confirmLogout"
        />
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
          <Password
            v-model="loginForm.password"
            autocomplete="current-password"
            :feedback="false"
            fluid
            required
          />
        </label>
        <Button type="submit" :label="loading ? '登录中' : '登录'" :disabled="loading || !loginForm.password" />
      </form>
    </section>

    <section v-else-if="!authChecked" class="section">
      <div class="empty">正在检查登录状态...</div>
    </section>

    <template v-else>
    <section v-if="activeTab === 'models'" class="section">
      <div class="section-head">
        <div>
          <h2>模型配置</h2>
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
              <small v-if="modelTestLatency(model)" class="cell-subtle">{{ modelTestLatency(model) }}ms</small>
              <small v-if="modelTestError(model)" class="cell-error" :title="modelTestError(model) ?? ''">
                {{ modelTestError(model) }}
              </small>
            </td>
            <td>{{ formatDateTime(model.lastTestedAt) }}</td>
            <td>
              <div class="row-actions">
                <Button label="编辑" severity="secondary" outlined size="small" @click="editModel(model)" />
                <Button
                  :label="isModelTesting(model.id) ? '测试中' : '测试'"
                  :icon="isModelTesting(model.id) ? 'pi pi-spin pi-spinner' : undefined"
                  severity="secondary"
                  outlined
                  size="small"
                  :disabled="isModelTesting(model.id)"
                  @click="testModel(model.id)"
                />
                <Button
                  v-if="hasModelTestRecord(model)"
                  label="日志"
                  icon="pi pi-code"
                  severity="secondary"
                  text
                  size="small"
                  @click="openModelTestRecord(model)"
                />
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
            <td>
              <div class="row-actions">
                <button type="button" class="secondary" @click="viewQuestions(set.id)">查看题目</button>
                <button type="button" class="secondary" @click="editBenchmarkSet(set)">编辑</button>
                <button type="button" class="danger" @click="confirmDeleteBenchmarkSet(set, $event)">删除</button>
              </div>
            </td>
          </tr>
          <tr v-if="!benchmarkSets.length">
            <td colspan="5" class="empty">暂无题集，请先导入</td>
          </tr>
        </tbody>
      </table>

      <div v-if="questions.length" class="detail-list">
        <div class="detail-head">
          <div>
            <h3>{{ selectedBenchmarkSet?.name ?? '题目预览' }}</h3>
            <p v-if="selectedBenchmarkSet">
              {{ selectedBenchmarkSet.category }} · {{ selectedBenchmarkSet.modality }} · {{ selectedBenchmarkSet.questionCount }} 题
            </p>
          </div>
          <button v-if="selectedBenchmarkSet" type="button" class="secondary" @click="editBenchmarkSet(selectedBenchmarkSet)">
            编辑题集名称
          </button>
        </div>
        <article v-for="question in questions" :key="question.id" class="question-row">
          <div class="question-meta">#{{ question.sourceRow }} · {{ questionTypeLabel(question.questionType) }}</div>
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
          <p>通过启动评测选择题集和模型，运行后可查看明细。</p>
        </div>
        <button type="button" :disabled="loading" @click="openRunDialog">启动评测</button>
      </div>

      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>题集</th>
            <th>模型</th>
            <th>Judge 模型</th>
            <th>评测状态</th>
            <th>进度</th>
            <th>得分</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="run in runs" :key="run.id">
            <td>#{{ run.id }}</td>
            <td>{{ run.benchmarkSetName || run.benchmarkSetId }}</td>
            <td>{{ run.modelNames.length ? run.modelNames.join('、') : '-' }}</td>
            <td>{{ run.judgeModelName || '-' }}</td>
            <td>
              <span :class="statusBadgeClass(run.status)">{{ formatStatus(run.status) }}</span>
            </td>
            <td>{{ run.completedCount }} / {{ run.totalCount }}</td>
            <td>{{ formatScore(run.accuracy) }}</td>
            <td>
              <div class="row-actions">
                <button type="button" class="secondary" @click="openRunDetails(run.id)">查看明细</button>
                <button v-if="canStopRun(run)" type="button" class="warning" @click="confirmStopRun(run, $event)">结束</button>
                <button v-if="canDeleteRun(run)" type="button" class="danger" @click="confirmDeleteRun(run, $event)">删除</button>
              </div>
            </td>
          </tr>
          <tr v-if="!runs.length">
            <td colspan="8" class="empty">暂无评测运行</td>
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
          <strong>{{ bestModelScore ? `${bestModelScore.modelName} · ${formatScore(bestModelScore.accuracy)}` : '-' }}</strong>
        </div>
        <div>
          <span>平均得分</span>
          <strong>{{ scoredModelScores.length ? formatScore(averageModelAccuracy) : '-' }}</strong>
        </div>
      </div>

      <div class="score-board">
        <Card
          v-for="score in sortedModelScores"
          :key="score.modelConfigId"
          class="score-card"
          :class="{ 'score-row-empty': !score.latestRunId || !score.scoredCount }"
        >
          <template #content>
            <div class="score-card-head">
              <div class="score-title">
                <h3>{{ score.modelName }}</h3>
                <p>{{ providerLabel(score.provider) }}</p>
              </div>
              <Tag
                class="score-state-tag"
                :severity="modelScoreTagSeverity(score)"
                :value="`评测状态：${formatOptionalStatus(score.latestRunStatus)}`"
              />
            </div>

            <div class="score-card-body">
              <div class="score-value">
                <span>最近得分</span>
                <strong>{{ modelScoreStatus(score) }}</strong>
              </div>
              <Button
                label="明细"
                size="small"
                severity="secondary"
                outlined
                :disabled="!score.latestRunId || loading"
                @click="score.latestRunId && openRunDetails(score.latestRunId)"
              />
            </div>

            <div class="score-progress-block">
              <div>
                <span>完成进度</span>
                <strong>{{ score.completedCount }} / {{ score.totalCount }}</strong>
              </div>
              <ProgressBar
                class="score-progress"
                :value="modelScoreProgressValue(score)"
                :show-value="false"
              />
            </div>

            <div class="score-meta">
              <span>题集：{{ score.benchmarkSetName || '-' }}</span>
              <span>运行：{{ score.latestRunId ? `#${score.latestRunId}` : '-' }}</span>
              <span>正确 / 计分：{{ score.correctCount }} / {{ score.scoredCount || score.totalCount }}</span>
              <span>时间：{{ formatDateTime(score.latestEvaluatedAt) }}</span>
            </div>
          </template>
        </Card>
        <div v-if="!modelScores.length" class="empty dashboard-empty">
          暂无模型配置
        </div>
      </div>
    </section>

    <Dialog
      :visible="benchmarkSetDialogOpen"
      modal
      header="编辑题集名称"
      class="app-dialog"
      :style="{ width: 'min(640px, calc(100vw - 32px))' }"
      @update:visible="(visible) => { if (!visible) closeBenchmarkSetDialog(); }"
    >
      <p class="dialog-description">类型和模态由导入文件判断，不在页面手动修改。</p>
      <form ref="benchmarkSetFormElement" class="dialog-form" @submit.prevent="saveBenchmarkSet">
        <label class="form-field">
          <span class="field-label">题集名称</span>
          <InputText v-model="benchmarkSetForm.name" required fluid />
        </label>
        <div class="readonly-fields">
          <span>类型：{{ benchmarkSetForm.category || '-' }}</span>
          <span>模态：{{ benchmarkSetForm.modality || '-' }}</span>
        </div>
      </form>
      <template #footer>
        <div class="dialog-actions">
          <Button label="取消" severity="secondary" outlined :disabled="loading" @click="closeBenchmarkSetDialog" />
          <Button label="保存名称" :disabled="loading" @click="benchmarkSetFormElement?.requestSubmit()" />
        </div>
      </template>
    </Dialog>

    <Dialog
      v-model:visible="detailDialogOpen"
      modal
      class="app-dialog run-detail-dialog"
      :style="{ width: 'min(1180px, calc(100vw - 32px))' }"
    >
      <template #header>
        <div>
          <h2>评测明细 #{{ detailRun?.id ?? detailRunId }}</h2>
          <div v-if="detailRun" class="modal-subhead">
            <span>{{ detailRun.benchmarkSetName || detailRun.benchmarkSetId }}</span>
            <span>模型：{{ detailRun.modelNames.length ? detailRun.modelNames.join('、') : '-' }}</span>
            <span>Judge：{{ detailRun.judgeModelName || '-' }}</span>
            <span :class="statusBadgeClass(detailRun.status)">评测状态：{{ formatStatus(detailRun.status) }}</span>
          </div>
        </div>
      </template>

      <div v-if="!detailRun" class="detail-loading">
        <i class="pi pi-spin pi-spinner" aria-hidden="true"></i>
        <span>正在加载评测运行...</span>
      </div>

      <div v-else-if="detailRun" class="modal-detail">
        <div class="run-detail-summary">
          <Card class="run-detail-metric">
            <template #content>
              <span>正确数量 / 总数量</span>
              <strong>{{ detailRun.correctCount }} / {{ detailRun.totalCount }}</strong>
            </template>
          </Card>
          <Card class="run-detail-metric">
            <template #content>
              <span>得分</span>
              <strong>{{ formatScore(detailRun.accuracy) }}</strong>
            </template>
          </Card>
          <Card class="run-detail-metric run-detail-metric-wide">
            <template #content>
              <div class="run-detail-status-line">
                <span>评测状态</span>
                <Tag :severity="runStatusTagSeverity(detailRun.status)" :value="formatStatus(detailRun.status)" />
              </div>
              <div class="run-detail-status-line">
                <span>完成进度</span>
                <strong>{{ detailRun.completedCount }} / {{ detailRun.totalCount }}</strong>
              </div>
              <ProgressBar
                class="run-detail-progress"
                :value="progressPercent(detailRun)"
                :show-value="false"
              />
            </template>
          </Card>
          <div class="run-detail-actions">
            <Button
              v-if="canStopRun(detailRun)"
              label="结束评测"
              severity="warn"
              outlined
              :disabled="loading"
              @click="confirmStopRun(detailRun, $event)"
            />
          </div>
        </div>

        <div v-if="detailResultsLoading" class="detail-loading detail-loading-table">
          <i class="pi pi-spin pi-spinner" aria-hidden="true"></i>
          <span>正在加载问答明细...</span>
        </div>

        <DataTable
          v-else
          :value="resultsForRun(detailRun.id)"
          data-key="id"
          paginator
          :rows="50"
          :rows-per-page-options="[50, 100, 200]"
          paginator-template="CurrentPageReport FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink RowsPerPageDropdown"
          current-page-report-template="共 {totalRecords} 条 · 第 {first} - {last} 条"
          scrollable
          scroll-height="flex"
          class="detail-data-table"
          size="small"
        >
          <Column field="questionSourceRow" header="题号" style="min-width: 80px">
            <template #body="{ data }">
              <div class="question-number-cell">
                <span>#{{ data.questionSourceRow ?? data.benchmarkQuestionId ?? data.id }}</span>
                <Button
                  icon="pi pi-info-circle"
                  text
                  rounded
                  severity="secondary"
                  size="small"
                  aria-label="查看题目"
                  @click="showQuestionPopover($event, data)"
                />
              </div>
            </template>
          </Column>
          <Column field="modelName" header="模型" style="min-width: 150px">
            <template #body="{ data }">
              {{ data.modelName || data.modelConfigId }}
            </template>
          </Column>
          <Column field="status" header="评测状态" style="min-width: 110px">
            <template #body="{ data }">
              <Tag :severity="runStatusTagSeverity(data.status)" :value="formatStatus(data.status)" />
            </template>
          </Column>
          <Column field="isCorrect" header="结果" style="min-width: 100px">
            <template #body="{ data }">
              <Tag v-if="data.status === 'judge_failed'" severity="warn" value="评分失败" />
              <Tag v-else-if="data.score !== null" severity="success" :value="`${Number(data.score).toFixed(2)} / ${Number(data.maxScore).toFixed(2)}`" />
              <Tag v-else-if="data.isCorrect === false" severity="danger" value="错误" />
              <Tag v-else severity="secondary" value="待评测" />
            </template>
          </Column>
          <Column field="latencyMs" header="耗时" style="min-width: 90px">
            <template #body="{ data }">
              {{ data.latencyMs ? `${data.latencyMs}ms` : '-' }}
            </template>
          </Column>
          <Column header="操作" style="min-width: 180px">
            <template #body="{ data }">
              <div class="row-actions">
                <Button
                  label="查看记录"
                  severity="secondary"
                  outlined
                  size="small"
                  @click="openResultRecord(data)"
                />
                <Button
                  v-if="canRetryResult(data)"
                  :label="isRetryingResult(data.id) ? '重试中' : '重试'"
                  severity="warn"
                  outlined
                  size="small"
                  :disabled="isRetryingResult(data.id)"
                  @click="retryResult(data)"
                />
              </div>
            </template>
          </Column>
          <template #empty>
            <div class="empty">暂无明细</div>
          </template>
        </DataTable>
        <Popover ref="questionPopover" class="question-popover">
          <div class="question-popover-content">
            <p>{{ formatQuestionPreview(questionPopoverResult) }}</p>
          </div>
        </Popover>
      </div>
    </Dialog>

    <Dialog
      :visible="selectedResultRecord !== null"
      modal
      class="app-dialog result-record-dialog"
      header="问答记录"
      :style="{ width: 'min(920px, calc(100vw - 32px))' }"
      @update:visible="(visible) => { if (!visible) closeResultRecord(); }"
    >
      <div v-if="selectedResultRecord" class="record-panel record-dialog-panel">
        <div class="record-grid">
          <div>
            <span>题号</span>
            <strong>#{{ selectedResultRecord.questionSourceRow ?? selectedResultRecord.benchmarkQuestionId ?? selectedResultRecord.id }}</strong>
          </div>
          <div>
            <span>模型</span>
            <strong>{{ selectedResultRecord.modelName || selectedResultRecord.modelConfigId }}</strong>
          </div>
          <div>
            <span>题目类型</span>
            <strong>{{ questionTypeLabel(selectedResultRecord.questionType) }}</strong>
          </div>
          <div>
            <span>评测状态</span>
            <strong>{{ formatStatus(selectedResultRecord.status) }}</strong>
          </div>
          <div>
            <span>得分</span>
            <strong>{{ selectedResultRecord.score !== null ? `${Number(selectedResultRecord.score).toFixed(2)} / ${Number(selectedResultRecord.maxScore).toFixed(2)}` : '-' }}</strong>
          </div>
          <div v-if="selectedResultRecord.judgeModelConfigId">
            <span>Judge 模型</span>
            <strong>{{ selectedResultRecord.judgeModelConfigId ? modelNameById(selectedResultRecord.judgeModelConfigId) : '-' }}</strong>
          </div>
          <div v-if="selectedResultRecord.judgeModelConfigId">
            <span>Judge 状态</span>
            <strong>{{ formatJudgeStatus(selectedResultRecord.judgeStatus) }}</strong>
          </div>
          <div v-if="selectedResultRecord.judgeModelConfigId">
            <span>Judge 得分比例</span>
            <strong>{{ selectedResultRecord.judgeScoreRatio !== null ? Number(selectedResultRecord.judgeScoreRatio).toFixed(2) : '-' }}</strong>
          </div>
        </div>
        <Panel header="题目">
          <pre>{{ selectedResultRecord.question || '暂无题目' }}</pre>
        </Panel>
        <Panel header="标准答案">
          <pre>{{ selectedResultRecord.expectedAnswer }}</pre>
        </Panel>
        <Panel>
          <template #header>
            <div class="record-panel-header">
              <span>AI 回复</span>
              <Button
                icon="pi pi-code"
                text
                rounded
                severity="secondary"
                size="small"
                aria-label="查看模型原始请求和响应"
                @click="openJsonRecordDialog('模型调用 JSON', modelRequestPayload(selectedResultRecord))"
              />
            </div>
          </template>
          <pre>{{ selectedResultRecord.modelAnswer || '暂无回复' }}</pre>
        </Panel>
        <Panel v-if="selectedResultRecord.judgeReason">
          <template #header>
            <div class="record-panel-header">
              <span>Judge 评分理由</span>
              <Button
                icon="pi pi-code"
                text
                rounded
                severity="secondary"
                size="small"
                aria-label="查看 Judge 原始请求和响应"
                @click="openJsonRecordDialog('Judge 调用 JSON', judgeRequestPayload(selectedResultRecord))"
              />
            </div>
          </template>
          <pre>{{ selectedResultRecord.judgeReason }}</pre>
        </Panel>
        <Panel v-if="selectedResultRecord.errorMessage" header="错误信息">
          <pre>{{ selectedResultRecord.errorMessage }}</pre>
        </Panel>
      </div>
    </Dialog>

    <Dialog
      :visible="jsonRecordDialog !== null"
      modal
      class="app-dialog json-record-dialog"
      :header="jsonRecordDialog?.title || 'JSON'"
      :style="{ width: 'min(900px, calc(100vw - 32px))' }"
      @update:visible="(visible) => { if (!visible) closeJsonRecordDialog(); }"
    >
      <pre class="json-record-content">{{ formatJson(jsonRecordDialog?.payload) }}</pre>
    </Dialog>

    <Dialog
      :visible="selectedModelTestRecord !== null"
      modal
      class="app-dialog json-record-dialog"
      :header="selectedModelTestRecord ? `模型测试日志：${selectedModelTestRecord.modelName}` : '模型测试日志'"
      :style="{ width: 'min(920px, calc(100vw - 32px))' }"
      @update:visible="(visible) => { if (!visible) closeModelTestRecord(); }"
    >
      <pre class="json-record-content">{{ formatJson(selectedModelTestRecord?.payload) }}</pre>
    </Dialog>

    <Dialog
      :visible="modelDialogOpen"
      modal
      class="app-dialog"
      :header="modelDialogTitle"
      :style="{ width: 'min(860px, calc(100vw - 32px))' }"
      @update:visible="(visible) => { if (!visible) closeModelDialog(); }"
    >
      <p class="dialog-description">
        {{ isEditingModel ? 'API Key 留空会保留原 Key。' : '配置模型服务商、模型名称和调用参数。' }}
      </p>

      <form ref="modelFormElement" class="dialog-form dialog-form-grid" @submit.prevent="saveModel">
        <label class="form-field">
          <span class="field-label">名称</span>
          <InputText v-model="modelForm.name" required placeholder="deepseek-v4-pro" fluid />
        </label>
        <label class="form-field">
          <span class="field-label">模型服务商</span>
          <Select
            v-model="modelForm.provider"
            :options="providerOptions"
            option-label="label"
            option-value="value"
            fluid
            @change="applyProviderPreset"
          />
        </label>
        <label class="form-field">
          <span class="field-label">模型</span>
          <Select
            v-model="modelForm.model"
            :options="modelOptionsForForm"
            required
            editable
            fluid
            @change="applyModelPreset"
          />
        </label>
        <label class="form-field">
          <span class="field-label">Base URL</span>
          <InputText v-model="modelForm.baseUrl" placeholder="https://api.example.com/v1" fluid />
        </label>
        <label class="form-field">
          <span class="field-label">API Key</span>
          <Password
            v-model="modelForm.apiKey"
            autocomplete="off"
            :feedback="false"
            toggle-mask
            fluid
            :placeholder="isEditingModel ? '留空则保留原 Key' : ''"
          />
        </label>
        <label v-if="isEditingModel" class="checkbox-row prime-checkbox-row">
          <Checkbox v-model="modelForm.clearApiKey" binary input-id="clear-api-key" />
          <span>清除 Key</span>
        </label>
        <div class="field-group">
          <span class="field-label">能力</span>
          <div class="capability-checks prime-checkbox-group">
            <label v-for="capability in capabilityOptions" :key="capability.value" class="checkbox-row prime-checkbox-row">
              <Checkbox v-model="modelForm.capabilities" :input-id="`capability-${capability.value}`" :value="capability.value" />
              <span>{{ capability.label }}</span>
            </label>
          </div>
        </div>
        <label class="form-field">
          <span class="field-label">Max Output Tokens</span>
          <InputNumber v-model="modelForm.maxOutputTokens" :min="128" :max="maxOutputTokensLimit" fluid />
        </label>
        <label class="checkbox-row prime-checkbox-row">
          <Checkbox v-model="modelForm.enabled" binary input-id="model-enabled" />
          <span>启用</span>
        </label>
      </form>

      <template #footer>
        <div class="dialog-actions">
          <Button label="取消" severity="secondary" outlined :disabled="loading" @click="closeModelDialog" />
          <Button
            :label="isEditingModel ? '更新模型' : '保存模型'"
            :disabled="loading"
            @click="modelFormElement?.requestSubmit()"
          />
        </div>
      </template>
    </Dialog>

    <Dialog
      :visible="runDialogOpen"
      modal
      header="启动评测"
      class="app-dialog"
      :style="{ width: 'min(640px, calc(100vw - 32px))' }"
      @update:visible="(visible) => { if (!visible) closeRunDialog(); }"
    >
      <p class="dialog-description">选择题集和一个或多个支持文本能力的模型后启动评测。</p>

      <div v-if="runCreateLoading" class="inline-loading">
        <i class="pi pi-spin pi-spinner" aria-hidden="true"></i>
        <span>正在启动评测...</span>
      </div>

      <label class="form-field run-dialog-field">
        <span class="field-label">题集</span>
        <Select
          v-model="selectedBenchmarkSetId"
          :disabled="runCreateLoading"
          :options="benchmarkSets"
          option-label="name"
          option-value="id"
          placeholder="请选择题集"
          fluid
        >
          <template #option="{ option }">
            <div class="select-option-stack">
              <strong>{{ option.name }}</strong>
              <small>{{ option.category }} · {{ option.modality }} · {{ option.questionCount }} 题 · {{ option.requiresJudge ? '问答题需 Judge' : '选择题无需 Judge' }}</small>
            </div>
          </template>
          <template #value="{ value }">
            <span>{{ benchmarkSetNameById(value) }}</span>
          </template>
        </Select>
      </label>

      <div class="modal-list run-model-list">
        <div v-for="model in runnableModels" :key="model.id" class="modal-model-row run-model-row">
          <div class="run-model-main">
            <Checkbox
              :model-value="selectedModelIds.includes(model.id)"
              :disabled="runCreateLoading"
              :input-id="`run-model-${model.id}`"
              binary
              @update:model-value="toggleRunModel(model.id)"
            />
            <label :for="`run-model-${model.id}`">
              <strong>{{ model.name }}</strong>
              <small>{{ providerLabel(model.provider) }}</small>
            </label>
          </div>
          <div class="run-model-status">
            <span
              v-tooltip.top="modelTestTooltip(model)"
              :class="['run-test-icon', isModelTestSuccessful(model) ? 'ok' : 'bad']"
              :aria-label="modelTestTooltip(model)"
            >
              <i :class="isModelTestSuccessful(model) ? 'pi pi-check' : 'pi pi-times'" aria-hidden="true"></i>
            </span>
            <small v-if="modelTestLatency(model)" class="cell-subtle">{{ modelTestLatency(model) }}ms</small>
            <Button
              :icon="isModelTesting(model.id) ? 'pi pi-spin pi-spinner' : 'pi pi-refresh'"
              severity="secondary"
              text
              rounded
              size="small"
              :aria-label="isModelTesting(model.id) ? '模型测试中' : '测试模型'"
              :disabled="runCreateLoading || isModelTesting(model.id)"
              @click="testModel(model.id)"
            />
          </div>
          <label
            v-if="selectedBenchmarkRequiresJudge && selectedModelIds.includes(model.id)"
            class="form-field run-judge-field"
          >
            <Select
              class="run-judge-select"
              :model-value="selectedJudgeModelId(model.id)"
              :options="judgeModelOptionsFor(model.id)"
              option-label="name"
              option-value="id"
              placeholder="请选择最近一次测试通过的模型"
              :disabled="runCreateLoading"
              fluid
              @update:model-value="(value) => setSelectedJudgeModelId(model.id, value)"
            >
              <template #option="{ option }">
                <div class="select-option-stack">
                  <strong>{{ option.name }}</strong>
                  <small>{{ providerLabel(option.provider) }}</small>
                </div>
              </template>
              <template #value="{ value }">
                <span>{{ value ? `${modelNameById(value)} · ${modelProviderTextById(value)}` : '请选择最近一次测试通过的模型' }}</span>
              </template>
            </Select>
          </label>
          <div v-else class="run-judge-placeholder"></div>
        </div>
      </div>

      <template #footer>
        <div class="dialog-actions">
          <Button label="取消" severity="secondary" outlined :disabled="runCreateLoading" @click="closeRunDialog" />
          <Button
            :label="runCreateLoading ? '启动中' : '确认启动'"
            :disabled="!canSubmitRun"
            @click="createRun"
          />
        </div>
      </template>
    </Dialog>
    </template>
  </main>
</template>
