import { createRouter, createWebHistory } from 'vue-router'
import { ModuleKey } from '@/types/conversation'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/', redirect: { name: ModuleKey.Interview } },
    {
      path: '/study',
      name: ModuleKey.Study,
      component: () => import('@/views/StudyRoom.vue'),
    },
    {
      path: '/interview',
      name: ModuleKey.Interview,
      component: () => import('@/views/InterviewRoom.vue'),
    },
    {
      path: '/note',
      name: ModuleKey.Note,
      component: () => import('@/views/NoteRoom.vue'),
    },
    { path: '/:pathMatch(.*)*', redirect: { name: ModuleKey.Interview } },
  ],
})

export default router
