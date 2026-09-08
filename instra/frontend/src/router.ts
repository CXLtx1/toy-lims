import { createRouter, createWebHistory } from "vue-router";
import SamplesView from "./views/SamplesView.vue";
import XrfView from "./views/XrfView.vue";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/samples" },
    { path: "/observatory", name: "observatory", component: () => import("./views/ObservatoryView.vue"),
      meta: { immersive: true } },
    { path: "/samples", name: "samples", component: SamplesView },
    { path: "/xrf", name: "xrf", component: XrfView },
  ],
});
