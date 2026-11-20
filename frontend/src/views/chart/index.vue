<template>
  <section class="page" data-module="chart">
    <header class="page-head">
      <div>
        <h2>图表配置管理</h2>
        <p class="page-desc">维护图表，围绕图表编号、图表名称、图表类型、数据来源做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记图表</button>
        <button class="btn" type="button" @click="exportRows">导出图表配置清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无图表配置数据，可先登记图表</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条图表配置记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <section class="field-dictionary">
      <header class="field-dict-head">
        <div>
          <h3>图表消费字段字典</h3>
          <p class="page-desc">同一显示名可能来自不同图表：这里按来源和图表编号列出类型、别名与可聚合口径。</p>
        </div>
        <div class="page-actions">
          <button class="btn" type="button" @click="exportFields">导出字段字典</button>
        </div>
      </header>

      <form class="filter-bar" @submit.prevent="reloadFields">
        <label class="filter-item">
          <span>字段名或别名</span>
          <input v-model="fieldKeyword" placeholder="按字段名或别名检索" />
        </label>
        <label class="filter-item">
          <span>类型</span>
          <select v-model="fieldType">
            <option value="">全部</option>
            <option value="数值">数值</option>
            <option value="字符">字符</option>
          </select>
        </label>
        <button class="btn" type="submit">查询字段</button>
        <button class="btn ghost" type="button" @click="resetFieldFilters">重置字段条件</button>
      </form>

      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in fieldColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, index) in fieldRows" :key="`${row.图表编号}-${row.字段名}-${index}`">
            <td v-for="column in fieldColumns" :key="column">{{ formatFieldValue((row as FieldRow)[column]) }}</td>
          </tr>
          <tr v-if="!fieldRows.length">
            <td :colspan="fieldColumns.length" class="empty-state">暂无字段字典数据</td>
          </tr>
        </tbody>
      </table>
      <p v-if="fieldReviews.length" class="error-text">
        名称碰撞待复核：{{ fieldReviews.map((item) => item.字段名).join('、') }}
      </p>
    </section>

    <Teleport to="body">
      <div v-if="showCreateModal" class="modal-overlay" @click.self="showCreateModal = false">
        <div class="modal-card">
          <header class="modal-head">
            <h3>登记图表</h3>
            <button class="btn ghost" type="button" @click="showCreateModal = false">&times;</button>
          </header>
          <form class="modal-body" @submit.prevent="submitCreate">
            <label v-for="field in columns.slice(0, 3)" :key="field" class="modal-field">
              <span>{{ field }}</span>
              <input v-model="createFields[field]" :placeholder="`请输入${field}`" required />
            </label>
            <footer class="modal-foot">
              <button class="btn" type="button" @click="showCreateModal = false">取消</button>
              <button class="btn primary" type="submit">提交登记</button>
            </footer>
          </form>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'
import { CHART_COLUMNS, CHART_FIELD_COLUMNS, formatFieldValue } from '@/api/fieldSpecs'

type Row = Record<string, string | number | null>

type FieldRow = Record<string, unknown>

const ENDPOINT = '/api/chart'
const FIELDS_ENDPOINT = '/api/chart/fields'
const columns = [...CHART_COLUMNS]
const fieldColumns = [...CHART_FIELD_COLUMNS]
const actions = ["保存配置", "发布图表", "停用图表"]
const statuses = ["草稿", "已配置", "已发布", "已停用"]
const stats = [{"label": "已发布图表", "value": 0}, {"label": "草稿图表", "value": 0}, {"label": "停用图表", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const showCreateModal = ref(false)
const createFields = ref<Record<string, string>>({})
const fieldRows = ref<FieldRow[]>([])
const fieldKeyword = ref('')
const fieldType = ref('')
const fieldReviews = ref<Record<string, unknown>[]>([])

function updateStats() {
  const data = rows.value
  stats.length > 0 && (stats[0].value = data.filter((r: Row) => r.status === statuses[1] || r.pending).length)
  stats.length > 1 && (stats[1].value = data.filter((r: Row) => r.status && !r.pending && !r.abnormal).length)
  stats.length > 2 && (stats[2].value = data.filter((r: Row) => r.abnormal).length)
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function exportFields() {
  window.open(`${FIELDS_ENDPOINT}/export`, '_blank')
}

function resetFieldFilters() {
  fieldKeyword.value = ''
  fieldType.value = ''
  void reloadFields()
}

async function reloadFields() {
  const query = new URLSearchParams()
  if (fieldKeyword.value.trim()) query.set('keyword', fieldKeyword.value.trim())
  if (fieldType.value) query.set('field_type', fieldType.value)
  try {
    const [response, reviews] = await Promise.all([
      request(`${FIELDS_ENDPOINT}?${query.toString()}`),
      request(`${FIELDS_ENDPOINT}/reviews`),
    ])
    const payload = response.ok ? await response.json() : { items: [] }
    fieldRows.value = payload.items ?? []
    const reviewPayload = reviews.ok ? await reviews.json() : { items: [] }
    fieldReviews.value = reviewPayload.items ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '字段字典读取失败'
  }
}

function openCreate() {
  errorMessage.value = ''
  createFields.value = {}
  showCreateModal.value = true
}

async function submitCreate() {
  errorMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: createFields.value }),
    })
    if (!response.ok) {
      const data = await response.json()
      throw new Error(data.message || '登记失败')
    }
    showCreateModal.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    if (!response.ok) {
      throw new Error('图表配置动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '图表配置操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('图表列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    updateStats()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '图表配置列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void reloadFields()
})
</script>
