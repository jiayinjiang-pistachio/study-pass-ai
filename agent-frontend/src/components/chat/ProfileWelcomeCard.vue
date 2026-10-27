<script setup lang="ts">
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { useProfileStore } from '@/stores/profile'

const MAX_LIST_ITEMS = 20
const MAX_ITEM_CHARS = 50
const MAX_YEARS = 60

const emit = defineEmits<{ skip: [] }>()

const profileStore = useProfileStore()
const formRef = ref<FormInstance>()
const submitting = ref(false)

const form = reactive({
  targetJob: profileStore.profile?.targetJob ?? '',
  yearsExperience: profileStore.profile?.yearsExperience ?? null,
  targetLevel: profileStore.profile?.targetLevel ?? '',
  targetSkills: [...(profileStore.profile?.targetSkills ?? [])],
  weakTopics: [...(profileStore.profile?.weakTopics ?? [])],
})

function validateYears(
  _rule: unknown,
  value: unknown,
  callback: (error?: Error) => void,
): void {
  // 0 是有效值（应届 / 无经验），只拦截 null 与越界
  if (typeof value !== 'number') {
    callback(new Error('请填写工作年限'))
    return
  }
  if (value < 0 || value > MAX_YEARS) {
    callback(new Error(`工作年限需在 0-${MAX_YEARS} 之间`))
    return
  }
  callback()
}

function validateList(
  _rule: unknown,
  value: unknown,
  callback: (error?: Error) => void,
): void {
  if (!Array.isArray(value)) {
    callback()
    return
  }
  if (value.length > MAX_LIST_ITEMS) {
    callback(new Error(`最多填写 ${MAX_LIST_ITEMS} 项`))
    return
  }
  if (
    value.some(
      (item) => typeof item === 'string' && item.trim().length > MAX_ITEM_CHARS,
    )
  ) {
    callback(new Error(`单项不超过 ${MAX_ITEM_CHARS} 字`))
    return
  }
  callback()
}

const rules: FormRules = {
  targetJob: [{ required: true, message: '请填写目标岗位', trigger: 'blur' }],
  yearsExperience: [{ validator: validateYears, trigger: 'change' }],
  targetLevel: [{ required: true, message: '请填写目标职级', trigger: 'blur' }],
  targetSkills: [{ validator: validateList, trigger: 'change' }],
  weakTopics: [{ validator: validateList, trigger: 'change' }],
}

function cleanItems(items: string[]): string[] {
  const result: string[] = []
  for (const item of items) {
    const text = item.trim()
    if (text && !result.includes(text)) result.push(text)
  }
  return result
}

async function handleSubmit(): Promise<void> {
  const formEl = formRef.value
  if (!formEl || submitting.value) return

  try {
    await formEl.validate()
  } catch {
    return
  }

  const years = form.yearsExperience
  if (years === null) return

  submitting.value = true
  try {
    await profileStore.save({
      target_job: form.targetJob.trim(),
      years_experience: years,
      target_level: form.targetLevel.trim(),
      target_skills: cleanItems(form.targetSkills),
      weak_topics: cleanItems(form.weakTopics),
    })
    ElMessage.success('画像已保存')
  } catch {
    // 请求层已统一提示错误，这里不重复弹出
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <section class="profile-card">
    <header class="profile-card__head">
      <h2 class="profile-card__title">先完善一下你的求职画像</h2>
      <p class="profile-card__desc">
        这些信息会用于个性化学习与面试建议；也可以先跳过，之后在对话中补充。
      </p>
    </header>

    <el-form
      ref="formRef"
      class="profile-card__form"
      :model="form"
      :rules="rules"
      label-position="top"
      @submit.prevent
    >
      <div class="profile-card__grid">
        <el-form-item label="目标岗位" prop="targetJob">
          <el-input
            v-model="form.targetJob"
            maxlength="64"
            placeholder="如：后端开发工程师"
          />
        </el-form-item>

        <el-form-item label="工作年限" prop="yearsExperience">
          <el-input-number
            v-model="form.yearsExperience"
            class="profile-card__number"
            :min="0"
            :max="MAX_YEARS"
            :step="1"
            controls-position="right"
            placeholder="0 表示应届 / 无经验"
          />
        </el-form-item>

        <el-form-item label="目标职级" prop="targetLevel">
          <el-input
            v-model="form.targetLevel"
            maxlength="32"
            placeholder="如：P6 / 高级工程师"
          />
        </el-form-item>
      </div>

      <el-form-item label="已掌握技能（选填）" prop="targetSkills">
        <el-select
          v-model="form.targetSkills"
          class="profile-card__select"
          multiple
          filterable
          allow-create
          default-first-option
          :reserve-keyword="false"
          placeholder="输入后回车添加，如 Python、MySQL"
        />
      </el-form-item>

      <el-form-item label="薄弱点（选填）" prop="weakTopics">
        <el-select
          v-model="form.weakTopics"
          class="profile-card__select"
          multiple
          filterable
          allow-create
          default-first-option
          :reserve-keyword="false"
          placeholder="输入后回车添加，如 分布式、系统设计"
        />
      </el-form-item>
    </el-form>

    <footer class="profile-card__actions">
      <el-button text @click="emit('skip')">稍后再说</el-button>
      <el-button type="primary" :loading="submitting" @click="handleSubmit">
        保存并开始
      </el-button>
    </footer>
  </section>
</template>

<style lang="scss" scoped>
.profile-card {
  width: 100%;
  padding: 24px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-bubble);
  background: var(--color-surface);

  &__head {
    margin-bottom: 18px;
  }

  &__title {
    font-size: 18px;
    font-weight: 600;
    color: var(--color-text);
  }

  &__desc {
    margin-top: 6px;
    font-size: 13px;
    line-height: 1.6;
    color: var(--color-text-muted);
  }

  &__grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0 16px;
  }

  &__number,
  &__select {
    width: 100%;
  }

  &__actions {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 12px;
    margin-top: 4px;
  }
}

@media (max-width: 768px) {
  .profile-card__grid {
    grid-template-columns: 1fr;
  }
}
</style>
