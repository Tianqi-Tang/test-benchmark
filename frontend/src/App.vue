<script setup lang="ts">
const textModels = [
  'AntAngelMed（安诊儿）',
  'DeepSeek-v4-pro',
  'qwen3.7-plus',
  'gpt-5.5',
  'Gemini-3.5-flash',
];

const multimodalModels = [
  'qwen3.7-plus',
  'gpt-5.5',
  'Gemini-3.5-flash',
];
</script>

<template>
  <main class="shell">
    <section class="panel">
      <div>
        <p class="eyebrow">Medical Model Evaluation</p>
        <h1>test-benchmark</h1>
        <p class="summary">医疗文本模型和多模态模型评测环境</p>
      </div>
      <div class="status" aria-label="service status">
        <span class="dot"></span>
        <span>测试环境待接入</span>
      </div>
    </section>

    <section class="grid" aria-label="candidate models">
      <article>
        <h2>通用文本模型</h2>
        <ul>
          <li v-for="model in textModels" :key="model">{{ model }}</li>
        </ul>
      </article>
      <article>
        <h2>多模态模型</h2>
        <ul>
          <li v-for="model in multimodalModels" :key="model">{{ model }}</li>
        </ul>
      </article>
    </section>
  </main>
</template>
