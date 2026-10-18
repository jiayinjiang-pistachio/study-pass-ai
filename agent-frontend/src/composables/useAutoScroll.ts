import { nextTick, onBeforeUnmount, onMounted, ref, watch, type Ref } from 'vue'

const NEAR_BOTTOM_THRESHOLD = 80

/**
 * 滚动容器自动贴底：新内容到达时，若用户原本就在底部则自动滚到底部；
 * 若用户已上滑查看历史，则不打扰，改为展示「回到最新」按钮。
 */
export function useAutoScroll(container: Ref<HTMLElement | null>, watchSource: () => unknown) {
  const showScrollToBottom = ref(false)

  function isNearBottom(el: HTMLElement): boolean {
    return el.scrollHeight - el.scrollTop - el.clientHeight <= NEAR_BOTTOM_THRESHOLD
  }

  function scrollToBottom(behavior: ScrollBehavior = 'smooth'): void {
    const el = container.value
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior })
    showScrollToBottom.value = false
  }

  function handleScroll(): void {
    const el = container.value
    if (!el) return
    showScrollToBottom.value = !isNearBottom(el)
  }

  watch(
    watchSource,
    async () => {
      const el = container.value
      if (!el) return
      const stick = isNearBottom(el)
      await nextTick()
      if (stick) scrollToBottom()
    },
    { deep: true },
  )

  onMounted(() => {
    scrollToBottom('auto')
    container.value?.addEventListener('scroll', handleScroll, { passive: true })
  })

  onBeforeUnmount(() => {
    container.value?.removeEventListener('scroll', handleScroll)
  })

  return { showScrollToBottom, scrollToBottom }
}
