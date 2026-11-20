<template>
  <section class="page" data-module="dashboard">
    <header class="page-head">
      <div>
        <h2>数据看板管理</h2>
        <p class="page-desc">维护看板配置，围绕看板编号、看板名称、包含图表、数据刷新做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记看板配置</button>
        <button class="btn" type="button" @click="exportRows">导出数据看板清单</button>
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
            <button class="link" type="button" @click="loadBindings(row)">查看横轴绑定</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无数据看板数据，可先登记看板配置</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条数据看板记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <section v-if="bindingItems.length || unboundItems.length || reviewItems.length" class="binding-panel">
      <h3>横轴绑定（按图表消费字段字典生成）</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>来源</th><th>图表编号</th><th>横轴</th><th>字段名</th><th>类型</th><th>可求和</th><th>状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(item, index) in bindingItems" :key="index">
            <td>{{ item.来源 }}</td>
            <td>{{ item.图表编号 }}</td>
            <td>{{ item.横轴 }}</td>
            <td>{{ item.字段名 }}</td>
            <td>{{ item.类型 }}</td>
            <td>{{ item.可求和 ? '是' : '否' }}</td>
            <td>{{ item.状态 }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="unboundItems.length" class="error-text">
        未绑定：{{ unboundItems.map((item) => `${item.横轴}（${item.未绑定原因}）`).join('、') }}
      </p>
      <p v-if="reviewItems.length" class="error-text">
        名称碰撞待复核：{{ reviewItems.map((item) => item.字段名).join('、') }}
      </p>
      <p v-if="bindingMessage" class="error-text">{{ bindingMessage }}</p>
    </section>

    <Teleport to="body">
      <div v-if="showCreateModal" class="modal-overlay" @click.self="showCreateModal = false">
        <div class="modal-card">
          <header class="modal-head">
            <h3>登记看板配置</h3>
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
import { DASHBOARD_COLUMNS } from '@/api/fieldSpecs'

type Row = Record<string, string | number | null>

type BindingItem = Record<string, unknown>

const ENDPOINT = '/api/dashboard'
const columns = [...DASHBOARD_COLUMNS]
const actions = ["完成配置", "发布看板", "下线看板"]
const statuses = ["待配置", "已发布", "展示中", "已下线"]
const stats = [{"label": "展示中看板", "value": 0}, {"label": "待配置看板", "value": 0}, {"label": "已下线看板", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const showCreateModal = ref(false)
const createFields = ref<Record<string, string>>({})
const bindingItems = ref<BindingItem[]>([])
const unboundItems = ref<BindingItem[]>([])
const reviewItems = ref<BindingItem[]>([])
const bindingMessage = ref('')

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

async function loadBindings(row: Row) {
  bindingMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/axis-bindings`)
    if (!response.ok) {
      throw new Error('横轴绑定生成失败')
    }
    const payload = await response.json()
    bindingItems.value = payload.items ?? []
    unboundItems.value = payload['未绑定项'] ?? []
    reviewItems.value = payload['待复核项'] ?? []
  } catch (error) {
    bindingMessage.value = error instanceof Error ? error.message : '横轴绑定生成失败'
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
      throw new Error('数据看板动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据看板操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('看板配置列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    updateStats()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据看板列表读取失败'
  }
}

onMounted(reload)
</script>
