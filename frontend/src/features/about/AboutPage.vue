<script setup lang="ts">
import { useAppState } from '../../app/state';
const app = useAppState();
</script>
<template>
  <section id="page-about" class="page" :class="{ active: app.page === 'about' }">
    <div class="panel about-panel">
      <h2>关于 LabFlow</h2>
      <div class="about-introduction">
        <p><b>LabFlow 并不是一个完整的 LIMS 系统，它只是一个实验室执行系统，可以理解为实验室管理系统的一个核心组件。</b></p>
        <p>系统仍会持续进行更新，若无法连接，大概率是在进行维护，可以联系开发人员。</p>
        <p>使用前建议阅读相关操作手册。实验方法、前处理条件、终点判断和质量控制要求仍以实验室现行标准为准，在正式版 LIMS 发布之前请以纸质版为准。</p>
      </div>
      <h3>使用前请注意</h3>
      <ol class="about-notices">
        <li><strong>按钮可见不代表当前用户具备权限，服务器会在执行时再次检查。</strong></li>
        <li><strong>每个用户的密码必须不同。</strong></li>
        <li><strong>有的地方是自动保存的，而有的地方需要手动保存，请务必注意。新建好后请确认是否新建成功。</strong></li>
        <li><strong>请分清楚终端与用户的区别。用户密码和终端密码用途不同，不应混用或共用。</strong></li>
        <li><strong>新建样品时，水分、煤、石膏、碳硫分析和量热请选择“其他”。</strong></li>
        <li><strong>分析项目框建议使用空格。可以输入氧化物等化合物。</strong></li>
        <li><strong>一个样品送到实验员，有几个溶样就建几个溶样。表格里的内容请务必与现实一一对应。</strong></li>
        <li><strong>如有必要，可以将溶样名改为玻璃器皿上的编号。</strong></li>
        <li><strong>一般情况下没有必要填写 XRF 的紫色框。</strong></li>
        <li><strong>其他样不能启用 XRF，也不能与常规样互相转换。已有专项数据后不能直接更换专项方法。</strong></li>
        <li><strong>并不建议在设置页建模板，建议在来样的详细清单中选择“保存当前方案”。</strong></li>
        <li><strong>LabFlow 提供权限控制、密码验证、审核状态和审计轨迹，但当前不等同于监管定义下的合规电子签名系统。</strong></li>
        <li><strong>为了方便使用，建议学习使用快捷键。Esc 键在不同场景下有不同作用。按数字键切换页面时务必注意光标是否在输入框中，按 Esc 即可将光标从输入框中移出。</strong></li>
        <li><strong>建议使用标签功能，方便使用和进行任务分配。样品小类（如 #实验样）、分组操作（如 #二组）建议使用，但并不强制。</strong></li>
        <li><strong>请注意分析项目的顺序和单位，这些都可以设置，且有模板可以使用。</strong></li>
        <li><strong>请有在设置页添加内容的勇气。如果你有需求，请务必考虑。模板能提高使用效率，请务必灵活运用。</strong></li>
        <li><strong>如果有问题，请务必询问其他实验员或与开发者交流；如有新功能需求或问题，务必与开发者沟通。</strong></li>
        <li><strong>有时页面内容需要一些时间进行加载，如样品页，这是正常的，如出现无法加载或出现报错弹窗，立刻联系开发或运维人员。</strong></li>
        <li><strong>各个仪器客户端软件需要手动打开，若出现离线，可以点击客户端软件的重新连接按钮。</strong></li>
        <li><strong>最后，效率是首位的，在效率的基础上尽量多使用本系统。无纸化并不是这个系统的目的，安全也不是这个项目的目的，合规性更不是这个项目的目的，效率是这个项目的目的。</strong></li>
      </ol>
      <h2>快捷键说明</h2>
      <p class="hint">在输入框中打字时单键快捷键自动失效；错误或授权对话框打开时不响应。</p>
      <div class="shortcut-grid">
        <div class="shortcut-item"><span class="shortcut-keys"><kbd>1</kbd>–<kbd>9</kbd></span><span>切换顶部页签</span></div>
        <div class="shortcut-item"><span class="shortcut-keys"><kbd>/</kbd></span><span>聚焦当前页搜索框</span></div>
        <div class="shortcut-item"><span class="shortcut-keys"><kbd>N</kbd></span><span>新建样品（仅来样页）</span></div>
        <div class="shortcut-item"><span class="shortcut-keys"><kbd>E</kbd></span><span>导出当前页 Excel</span></div>
        <div class="shortcut-item"><span class="shortcut-keys"><kbd>[</kbd> <kbd>]</kbd></span><span>列表上一页 / 下一页（来样、结果）</span></div>
        <div class="shortcut-item"><span class="shortcut-keys"><kbd>Esc</kbd></span><span>输入框失焦；结果页再按一次收起最近展开的样品</span></div>
        <div class="shortcut-item"><span class="shortcut-keys"><kbd>Ctrl</kbd>+<kbd>C</kbd> / <kbd>Ctrl</kbd>+<kbd>D</kbd></span><span>表格复制选区 / 向下填充（数据页）</span></div>
      </div>
    </div>
  </section>
</template>
