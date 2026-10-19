import { createRouter, createWebHistory } from 'vue-router'
import { ModuleKey } from '@/types/conversation'
import { hasToken } from '@/utils/token'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { public: true },
    },
    {
      path: '/',
      component: () => import('@/layouts/AppShell.vue'),
      redirect: { name: ModuleKey.Interview },
      children: [
        {
          path: 'study',
          name: ModuleKey.Study,
          component: () => import('@/views/StudyRoom.vue'),
        },
        {
          path: 'interview',
          name: ModuleKey.Interview,
          component: () => import('@/views/InterviewRoom.vue'),
        },
        {
          path: 'note',
          name: ModuleKey.Note,
          component: () => import('@/views/NoteRoom.vue'),
        },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: { name: ModuleKey.Interview } },
  ],
})

// 前置守卫：未登录只能访问公开路由，已登录不再回到登录页
router.beforeEach((to) => {
  const loggedIn = hasToken()

  if (to.name === 'login') {
    return loggedIn ? { name: ModuleKey.Interview } : true
  }

  if (!loggedIn) {
    return {
      name: 'login',
      query: to.fullPath === '/' ? {} : { redirect: to.fullPath },
    }
  }

  return true
})

export default router
