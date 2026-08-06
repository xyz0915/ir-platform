/**
 * QA 独立复验 · LoginView 认证链路行为测试（login-replace 专项）
 *
 * 背景：views-smoke / router-reachability 均不覆盖 /login，本文件补齐
 * 登录页关键行为断言（设计 §10 A1-A6、A11）：
 *   - 协议门槛（按钮禁用 + Enter 拦截，防绕过）
 *   - 提交链（authStore.login(form.username, form.password) — 2 参、字段名 1:1）
 *   - 成功流（ElMessage.success('登录成功') + router.push('/')）
 *   - 必填校验（blur trigger，校验失败不发请求）
 *   - 回车提交（@keyup.enter）
 *   - loading 防重复提交
 *   - 品牌区渲染（BrandArt SVG 挂载）
 *
 * 运行：npx vitest run src/__tests__/verify/login-view.spec.js
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import LoginView from '@/views/LoginView.vue'

// ── Mock：authStore.login / router.push（hoisted 保证 vi.mock 工厂可引用）──
const { loginMock, pushMock } = vi.hoisted(() => ({
  loginMock: vi.fn(),
  pushMock: vi.fn()
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ login: loginMock })
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: pushMock })
}))

// ── Element Plus 消息 spy（保留真实组件，贴近生产）──
const successSpy = vi.spyOn(ElMessage, 'success')
const warningSpy = vi.spyOn(ElMessage, 'warning')

function mountLogin() {
  return mount(LoginView, {
    global: { plugins: [ElementPlus] }
  })
}

// 注：happy-dom + ElementPlus 下 el-input 的 id 不透传到内部 input，
// 按渲染顺序取 input：0=用户名, 1=密码, 2=协议 checkbox（id 保留）。
function usernameInput(wrapper) {
  return wrapper.findAll('input')[0]
}
function passwordInput(wrapper) {
  return wrapper.findAll('input')[1]
}
function agreeCheckbox(wrapper) {
  return wrapper.find('#login-agree')
}

async function fillCredentials(wrapper, username = 'admin', password = 'admin123') {
  await usernameInput(wrapper).setValue(username)
  await passwordInput(wrapper).setValue(password)
}

describe('LoginView 认证链路行为（QA 独立复验）', () => {
  beforeEach(() => {
    loginMock.mockReset()
    pushMock.mockReset()
    successSpy.mockClear()
    warningSpy.mockClear()
    loginMock.mockResolvedValue({ code: 0, data: { token: 't', user: { id: 1 } } })
  })

  it('A11 默认渲染：品牌区 BrandArt SVG + 登录卡关键元素齐全', () => {
    const wrapper = mountLogin()
    expect(wrapper.find('.login-brand svg.hero-art').exists()).toBe(true)
    expect(wrapper.find('.brand-title').text()).toContain('应急平台')
    expect(wrapper.find('.brand-title').text()).toContain('安全护航')
    expect(wrapper.find('.brand-sub').text()).toContain('实时监测')
    expect(wrapper.find('.card-head h2').text()).toBe('应急运营门户')
    expect(wrapper.find('.card-sub').text()).toContain('统一身份认证')
    expect(wrapper.findAll('.el-input input').length).toBe(2)
    expect(usernameInput(wrapper).attributes('type')).toBe('text')
    expect(passwordInput(wrapper).attributes('type')).toBe('password')
    expect(agreeCheckbox(wrapper).exists()).toBe(true)
    expect(wrapper.find('.login-submit').text()).toContain('登录')
    expect(wrapper.find('.card-foot').text()).toContain('登录遇到问题？请联系平台管理员')
    // 默认勾选 → 按钮可用
    expect(wrapper.find('.login-submit').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('A3 空校验：validate 失败（valid=false）时不发请求（源码拦截分支）', async () => {
    // 注：happy-dom 下 el-form 的 required 校验不生效（validate 恒 true），
    // 已单独验证 async-validator 对空必填返回失败（message=请输入用户名）。
    // 此处直接验证 LoginView 的拦截分支：valid=false → 不发请求。
    const wrapper = mountLogin()
    const formRef = wrapper.vm.formRef
    formRef.validate = (cb) => {
      cb(false)
      return Promise.resolve(false)
    }
    await wrapper.find('.login-submit').trigger('click')
    await flushPromises()
    expect(loginMock).not.toHaveBeenCalled()
    expect(pushMock).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('A1 提交链 + 成功流：login 接收 (username, password) 2 参 → success → push /', async () => {
    const wrapper = mountLogin()
    await fillCredentials(wrapper, 'admin', 'admin123')
    await wrapper.find('.login-submit').trigger('click')
    await flushPromises()
    expect(loginMock).toHaveBeenCalledTimes(1)
    expect(loginMock).toHaveBeenCalledWith('admin', 'admin123')
    expect(successSpy).toHaveBeenCalledWith('登录成功')
    expect(pushMock).toHaveBeenCalledWith('/')
    wrapper.unmount()
  })

  it('A4 协议门槛-按钮：取消勾选 → 按钮 disabled、点击不发请求', async () => {
    const wrapper = mountLogin()
    await agreeCheckbox(wrapper).setValue(false)
    expect(wrapper.find('.login-submit').attributes('disabled')).toBeDefined()
    await wrapper.find('.login-submit').trigger('click')
    await flushPromises()
    expect(loginMock).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('A4 协议门槛-Enter 绕过：未勾选时回车 → warning 提示、不发请求', async () => {
    const wrapper = mountLogin()
    await fillCredentials(wrapper, 'admin', 'admin123')
    await agreeCheckbox(wrapper).setValue(false)
    await passwordInput(wrapper).trigger('keyup.enter')
    await flushPromises()
    expect(warningSpy).toHaveBeenCalledWith('请先阅读并同意用户协议和隐私政策声明')
    expect(loginMock).not.toHaveBeenCalled()
    expect(pushMock).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('A5 回车提交：密码框 Enter → 触发登录（与点击等效）', async () => {
    const wrapper = mountLogin()
    await fillCredentials(wrapper, 'admin', 'admin123')
    await passwordInput(wrapper).trigger('keyup.enter')
    await flushPromises()
    expect(loginMock).toHaveBeenCalledWith('admin', 'admin123')
    expect(pushMock).toHaveBeenCalledWith('/')
    wrapper.unmount()
  })

  it('A6 loading：提交期间按钮 is-loading，完成后复位', async () => {
    let resolveLogin
    loginMock.mockImplementation(() => new Promise((r) => { resolveLogin = r }))
    const wrapper = mountLogin()
    await fillCredentials(wrapper, 'admin', 'admin123')
    await wrapper.find('.login-submit').trigger('click')
    // 等 validate 完成、login 被调用；login 的 pending Promise 不 resolve → loading 保持 true
    await flushPromises()
    expect(loginMock).toHaveBeenCalled()
    expect(wrapper.find('.login-submit').classes()).toContain('is-loading')
    resolveLogin({ code: 0, data: { token: 't', user: {} } })
    await flushPromises()
    expect(wrapper.find('.login-submit').classes()).not.toContain('is-loading')
    wrapper.unmount()
  })
})
