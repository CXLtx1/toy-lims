import { createApp } from 'vue';
import App from './App.vue';
import { showError } from './app/dialogs';
import '../../server/static/style.css';

const app = createApp(App);
app.config.errorHandler = error => showError(error, '界面运行错误');
app.mount('#app');
