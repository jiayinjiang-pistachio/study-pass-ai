<script setup lang="ts"></script>

<template>
  <span class="loading-dots" aria-label="正在输入">
    <i class="loading-dots__dot" />
    <i class="loading-dots__dot" />
    <i class="loading-dots__dot" />
  </span>
</template>

<style lang="scss" scoped>
.loading-dots {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 22px;

  &__dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: #b8bec8;
    animation: loading-bounce 1.2s infinite ease-in-out;

    &:nth-child(2) {
      animation-delay: 0.16s;
    }

    &:nth-child(3) {
      animation-delay: 0.32s;
    }
  }
}

@keyframes loading-bounce {
  0%,
  60%,
  100% {
    transform: translateY(0);
    opacity: 0.5;
  }

  30% {
    transform: translateY(-4px);
    opacity: 1;
  }
}
</style>
