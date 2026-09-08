import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Session } from './types';

const sessionData: Session = {
  ok: true, csrf_token: 'csrf-one', authenticated: true, setup_required: false,
  terminal: null, user: null, authorization_required: true, requireHTTPS: false, min_password_length: 8,
};
const response = (data: unknown, status = 200, headers?: HeadersInit) =>
  new Response(JSON.stringify(data), { status, headers });
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}

let client: typeof import('./client');
let dialogs: typeof import('../app/dialogs');
let fetchMock: ReturnType<typeof vi.fn<typeof fetch>>;

beforeEach(async () => {
  vi.resetModules();
  fetchMock = vi.fn<typeof fetch>();
  vi.stubGlobal('fetch', fetchMock);
  dialogs = await import('../app/dialogs');
  client = await import('./client');
});
afterEach(() => {
  dialogs.finishAuthorization(false);
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

async function boot() {
  fetchMock.mockResolvedValueOnce(response(sessionData));
  await client.bootstrapSession();
  fetchMock.mockClear();
}

describe('session bootstrap and CSRF', () => {
  it('shares a single bootstrap between boot and concurrent writes, then caches the token', async () => {
    const pending = deferred<Response>();
    fetchMock.mockReturnValueOnce(pending.promise).mockImplementation(async () => response({ ok: true }));
    const session = client.bootstrapSession();
    const first = client.request('/api/one', { method: 'post', body: { value: 1 } });
    const second = client.request('/api/two', { method: 'PATCH', body: { value: 2 } });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(client.network.writes).toBe(2);
    pending.resolve(response(sessionData));
    await Promise.all([session, first, second]);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[0]?.[0]).toBe(`${location.origin}/api/session`);
    for (const [, init] of fetchMock.mock.calls.slice(1)) {
      expect(init).toMatchObject({ credentials: 'same-origin', cache: 'no-store', headers: {
        'X-CSRF-Token': 'csrf-one', 'Content-Type': 'application/json',
      } });
    }
    expect(fetchMock.mock.calls[1]?.[1]?.body).toBe('{"value":1}');
    expect(await client.bootstrapSession()).toEqual(sessionData);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(client.network.writes).toBe(0);
    expect(client.network.lastWrite).toBeGreaterThan(0);
  });

  it('shares a forced refresh and uses the refreshed token', async () => {
    await boot();
    const pending = deferred<Response>();
    fetchMock.mockReturnValueOnce(pending.promise).mockResolvedValueOnce(response({ ok: true }));
    const first = client.bootstrapSession(true);
    const second = client.bootstrapSession(true);
    pending.resolve(response({ ...sessionData, csrf_token: 'csrf-two' }));
    await Promise.all([first, second]);
    await client.request('/api/save', { method: 'PUT' });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1]?.[1]?.headers).toEqual({ 'X-CSRF-Token': 'csrf-two' });
  });

  it('clears a failed bootstrap singleflight so a later attempt can succeed', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('offline'));
    const results = await Promise.allSettled([client.bootstrapSession(), client.bootstrapSession()]);
    expect(results.map(result => result.status)).toEqual(['rejected', 'rejected']);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    fetchMock.mockResolvedValueOnce(response(sessionData));
    await expect(client.bootstrapSession()).resolves.toEqual(sessionData);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it.each([
    null, [], {}, { ...sessionData, csrf_token: 7 },
    { ...sessionData, authenticated: 'true' }, { ...sessionData, setup_required: null },
  ].map(data => ({ data })))('rejects malformed session data: $data', async ({ data }) => {
    fetchMock.mockResolvedValueOnce(response(data));
    await expect(client.bootstrapSession()).rejects.toMatchObject({ code: 'invalid_response' });
  });

  it.each([[false, false, true], [false, true, false], [true, false, false]])(
    'sets sessionLost for authenticated=%s, setup_required=%s', async (authenticated, setup_required, lost) => {
      fetchMock.mockResolvedValueOnce(response({ ...sessionData, authenticated, setup_required }));
      await client.bootstrapSession();
      expect(client.network.sessionLost).toBe(lost);
    },
  );

  it('does not bootstrap or add write headers for a GET', async () => {
    fetchMock.mockResolvedValueOnce(response({ items: [] }));
    await expect(client.request('/api/items')).resolves.toEqual({ items: [] });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({ method: 'GET', headers: {} });
    expect(client.network).toMatchObject({ writes: 0, lastWrite: 0 });
  });

  it.each(['https://other.example/api/items', '/login', '/apiary/items'])('rejects unsafe URL %s', async url => {
    await expect(client.request(url)).rejects.toBeInstanceOf(client.ApiError);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('errors and write safety', () => {
  it.each([400, 401, 403, 409, 422, 429, 500, 503])('does not replay a failed write with HTTP %s', async status => {
    await boot();
    const body = { name: 'unsaved draft', values: [1, 2] };
    fetchMock.mockResolvedValueOnce(response({ error: 'save rejected', code: 'save_failed' }, status, { 'Retry-After': '12' }));
    await expect(client.request('/api/save', { method: 'POST', body })).rejects.toMatchObject({
      name: 'ApiError', status, code: 'save_failed', message: 'save rejected', retryAfter: 12,
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(body).toEqual({ name: 'unsaved draft', values: [1, 2] });
    expect(client.network.writes).toBe(0);
    expect(client.network.sessionLost).toBe(status === 401);
  });

  it('invalidates a rejected CSRF token without replaying the write', async () => {
    await boot();
    fetchMock.mockResolvedValueOnce(response({ code: 'csrf_invalid' }, 403));
    await expect(client.request('/api/save', { method: 'POST' })).rejects.toMatchObject({ code: 'csrf_invalid' });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    fetchMock.mockResolvedValueOnce(response({ ...sessionData, csrf_token: 'replacement' }))
      .mockResolvedValueOnce(response({ ok: true }));
    await client.request('/api/save', { method: 'POST' });
    expect(fetchMock.mock.calls[1]?.[0]).toBe(`${location.origin}/api/session`);
    expect(fetchMock.mock.calls[2]?.[1]?.headers).toEqual({ 'X-CSRF-Token': 'replacement' });
  });

  it('treats ok:false as failure even for HTTP 200', async () => {
    fetchMock.mockResolvedValueOnce(response({ ok: false, error: 'not saved', code: 'validation' }));
    await expect(client.request('/api/items')).rejects.toMatchObject({ status: 200, code: 'validation' });
  });

  it('ignores non-numeric Retry-After rather than returning NaN', async () => {
    fetchMock.mockResolvedValueOnce(response({}, 429, { 'Retry-After': 'Wed, 21 Oct 2015 07:28:00 GMT' }));
    await expect(client.request('/api/items')).rejects.toMatchObject({ status: 429, retryAfter: null });
  });

  it.each([200, 500])('reports invalid JSON at HTTP %s without retrying', async status => {
    await boot();
    fetchMock.mockResolvedValueOnce(new Response('<html>proxy error</html>', { status }));
    await expect(client.request('/api/save', { method: 'POST' })).rejects.toMatchObject({ status, code: 'invalid_response' });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(client.network.writes).toBe(0);
  });

  it('marks a non-JSON 401 as session loss too', async () => {
    fetchMock.mockResolvedValueOnce(new Response('login required', { status: 401 }));
    await expect(client.request('/api/items')).rejects.toMatchObject({ status: 401, code: 'invalid_response' });
    expect(client.network.sessionLost).toBe(true);
  });

  it('accepts an empty 204 response', async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await expect(client.request('/api/items')).resolves.toEqual({});
  });

  it.each([false, true])('a wrong operator password preserves sessionLost=%s', async lost => {
    await boot();
    client.network.sessionLost = lost;
    fetchMock.mockResolvedValueOnce(response({ error: 'wrong password' }, 401));
    await expect(client.request('/api/authorize', { method: 'POST', body: { password: 'wrong' } }))
      .rejects.toMatchObject({ status: 401 });
    expect(client.network.sessionLost).toBe(lost);
  });
});

describe('authorization-required writes', () => {
  it.each([true, false])('coalesces concurrent prompts and handles allowed=%s without losing bodies', async allowed => {
    await boot();
    const prompt = vi.spyOn(dialogs, 'requestAuthorization');
    fetchMock.mockResolvedValueOnce(response({ code: 'authorization_required', error: 'confirm operator' }, 428))
      .mockResolvedValueOnce(response({ code: 'authorization_required' }, 428))
      .mockImplementation(async () => response({ ok: true }));
    const bodies = [{ draft: 'first' }, { draft: 'second' }];
    const pending = Promise.allSettled(bodies.map((body, index) => client.request(`/api/save/${index}`, { method: 'POST', body })));
    await vi.waitFor(() => expect(prompt).toHaveBeenCalledTimes(2));
    expect(prompt.mock.results[0]?.value).toBe(prompt.mock.results[1]?.value);
    expect(dialogs.dialogs).toMatchObject({ authorization: true, explanation: 'confirm operator' });
    expect(client.network.writes).toBe(2);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    dialogs.finishAuthorization(allowed);
    const results = await pending;
    expect(results.map(result => result.status)).toEqual(allowed ? ['fulfilled', 'fulfilled'] : ['rejected', 'rejected']);
    if (allowed) {
      expect(fetchMock).toHaveBeenCalledTimes(4);
      expect(fetchMock.mock.calls.map(([, init]) => init?.body)).toEqual([
        JSON.stringify(bodies[0]), JSON.stringify(bodies[1]), JSON.stringify(bodies[0]), JSON.stringify(bodies[1]),
      ]);
    } else {
      expect(fetchMock).toHaveBeenCalledTimes(2);
      for (const result of results) {
        if (result.status === 'rejected') expect(result.reason).toMatchObject({ status: 428, code: 'authorization_cancelled' });
      }
    }
    expect(bodies).toEqual([{ draft: 'first' }, { draft: 'second' }]);
    expect(client.network.writes).toBe(0);
    expect(dialogs.dialogs.authorization).toBe(false);
  });

  it('retries at most once even if authorization is required again', async () => {
    await boot();
    const prompt = vi.spyOn(dialogs, 'requestAuthorization');
    fetchMock.mockImplementation(async () => response({ code: 'authorization_required' }, 428));
    const pending = expect(client.request('/api/save', { method: 'POST' })).rejects.toMatchObject({ status: 428, code: 'authorization_required' });
    await vi.waitFor(() => expect(dialogs.dialogs.authorization).toBe(true));
    dialogs.finishAuthorization(true);
    await pending;
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(prompt).toHaveBeenCalledTimes(1);
  });

  it.each([
    { url: '/api/save', authorize: false, code: 'authorization_required' },
    { url: '/api/authorize', authorize: true, code: 'authorization_required' },
    { url: '/api/save', authorize: true, code: 'other_precondition' },
  ])('does not prompt for $url with authorize=$authorize and code=$code', async ({ url, authorize, code }) => {
    await boot();
    fetchMock.mockResolvedValueOnce(response({ code }, 428));
    await expect(client.request(url, { method: 'POST', authorize })).rejects.toMatchObject({ status: 428, code });
    expect(dialogs.dialogs.authorization).toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('does not replay a write aborted while the authorization prompt is open', async () => {
    await boot();
    const controller = new AbortController();
    fetchMock.mockResolvedValueOnce(response({ code: 'authorization_required' }, 428));
    const pending = expect(client.request('/api/save', { method: 'POST', signal: controller.signal })).rejects.toMatchObject({ name: 'AbortError' });
    await vi.waitFor(() => expect(dialogs.dialogs.authorization).toBe(true));
    controller.abort();
    dialogs.finishAuthorization(true);
    await pending;
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(client.network.writes).toBe(0);
  });
});

describe('uploads', () => {
  it('sends multipart data and CSRF without overriding the browser boundary', async () => {
    await boot();
    const file = new File(['workbook'], 'SAMPLES.XLSX');
    fetchMock.mockResolvedValueOnce(response({ imported: 1 }));
    await expect(client.upload('/api/import', file)).resolves.toEqual({ imported: 1 });
    const init = fetchMock.mock.calls[0]?.[1];
    expect(init).toMatchObject({ method: 'POST', headers: { 'X-CSRF-Token': 'csrf-one' }, credentials: 'same-origin' });
    expect(new Headers(init?.headers).has('Content-Type')).toBe(false);
    expect(init?.body).toBeInstanceOf(FormData);
    expect((init?.body as FormData).get('file')).toBe(file);
  });

  it('reuses the same multipart body after authorization', async () => {
    await boot();
    fetchMock.mockResolvedValueOnce(response({ code: 'authorization_required' }, 428))
      .mockResolvedValueOnce(response({ imported: 1 }));
    const pending = client.upload('/api/import', new File(['workbook'], 'samples.xlsx'));
    await vi.waitFor(() => expect(dialogs.dialogs.authorization).toBe(true));
    dialogs.finishAuthorization(true);
    await pending;
    expect(fetchMock.mock.calls[1]?.[1]?.body).toBe(fetchMock.mock.calls[0]?.[1]?.body);
    expect(new Headers(fetchMock.mock.calls[1]?.[1]?.headers).has('Content-Type')).toBe(false);
  });

  it.each(['samples.csv', 'samples.xlsx.exe'])('rejects unsupported filename %s before network access', async name => {
    await expect(client.upload('/api/import', new File(['x'], name))).rejects.toBeInstanceOf(client.ApiError);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(client.network.writes).toBe(0);
  });

  it('rejects files over 20 MiB before network access', async () => {
    const file = new File(['x'], 'samples.xlsx');
    Object.defineProperty(file, 'size', { value: 20 * 1024 * 1024 + 1 });
    await expect(client.upload('/api/import', file)).rejects.toBeInstanceOf(client.ApiError);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('timeout and cancellation', () => {
  it('reports network failure without retrying a possibly completed write', async () => {
    await boot();
    fetchMock.mockRejectedValueOnce(new TypeError('connection reset'));
    await expect(client.request('/api/save', { method: 'POST' })).rejects.toMatchObject({ code: 'network_error', status: 0 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(client.network.writes).toBe(0);
  });

  it('aborts a timed-out write, warns of uncertain completion, and never retries', async () => {
    await boot();
    vi.useFakeTimers();
    fetchMock.mockImplementation((_url, init) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(init.signal?.reason), { once: true });
    }));
    const pending = expect(client.request('/api/save', { method: 'POST', timeout: 25 })).rejects.toMatchObject({
      code: 'timeout', status: 0, message: expect.stringContaining('\u5199\u5165\u53ef\u80fd\u5df2\u7ecf\u5b8c\u6210'),
    });
    await vi.advanceTimersByTimeAsync(25);
    await pending;
    expect(fetchMock.mock.calls[0]?.[1]?.signal?.aborted).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(client.network.writes).toBe(0);
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each([false, true])('preserves caller abort reason (already aborted=%s) and cleans up', async alreadyAborted => {
    await boot();
    vi.useFakeTimers();
    const controller = new AbortController();
    const reason = new DOMException('leaving page', 'AbortError');
    const removeListener = vi.spyOn(controller.signal, 'removeEventListener');
    const started = deferred<void>();
    fetchMock.mockImplementation((_url, init) => new Promise((_resolve, reject) => {
      started.resolve();
      if (init?.signal?.aborted) reject(init.signal.reason);
      else init?.signal?.addEventListener('abort', () => reject(init.signal?.reason), { once: true });
    }));
    if (alreadyAborted) controller.abort(reason);
    const pending = expect(client.request('/api/save', { method: 'POST', signal: controller.signal })).rejects.toBe(reason);
    await started.promise;
    if (!alreadyAborted) controller.abort(reason);
    await pending;
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(client.network.writes).toBe(0);
    expect(removeListener).toHaveBeenCalledWith('abort', expect.any(Function));
    expect(vi.getTimerCount()).toBe(0);
  });

  it('clears the timeout and caller listener after success', async () => {
    vi.useFakeTimers();
    const controller = new AbortController();
    const removeListener = vi.spyOn(controller.signal, 'removeEventListener');
    fetchMock.mockResolvedValueOnce(response({ ok: true }));
    await client.request('/api/items', { signal: controller.signal });
    expect(vi.getTimerCount()).toBe(0);
    expect(removeListener).toHaveBeenCalledWith('abort', expect.any(Function));
  });
});
