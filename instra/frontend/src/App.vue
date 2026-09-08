<template>
  <n-config-provider :locale="zhCN" :date-locale="dateZhCN" :theme-overrides="themeOverrides">
    <n-message-provider>
      <n-dialog-provider>
        <div class="app-shell" :class="{ 'immersive-shell': route.meta.immersive }">
          <header v-if="!route.meta.immersive" class="app-header">
            <div class="brand">
              <span class="brand-mark">◇</span>
              <span class="brand-name">insta</span>
              <span class="brand-sub">样品与仪器数据浏览</span>
            </div>
            <nav class="nav">
              <router-link to="/observatory" class="nav-link" active-class="active">实验星港</router-link>
              <router-link to="/samples" class="nav-link" active-class="active">样品聚合</router-link>
              <router-link to="/xrf" class="nav-link" active-class="active">XRF 数据</router-link>
            </nav>
          </header>
          <main class="app-main">
            <router-view />
          </main>
        </div>
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { dateZhCN, NConfigProvider, NDialogProvider, NMessageProvider, zhCN } from "naive-ui";
import { useRoute } from "vue-router";

const route = useRoute();

const themeOverrides = {
  common: {
    primaryColor: "#2b6cb0",
    primaryColorHover: "#3182ce",
    borderRadius: "8px",
    fontSize: "13px",
  },
};
</script>
