// Run the compiled resident controller against the test's real local HTTP listener.
// Only native WeChat transport/storage/payment-panel APIs are adapted here.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const [compiled, stateFile, phase] = process.argv.slice(2);
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const storage = new Map(
  fs.existsSync(stateFile)
    ? JSON.parse(fs.readFileSync(stateFile, 'utf8'))
    : [],
);
storage.set('xlife:' + input.base + ':resident-session', {
  token: input.token,
  userId: input.userId,
  expiresAt: new Date(Date.now() + 3600000).toISOString(),
});
const requests = [];
const panels = [];
let dropCreationResponse = phase === 'create';
let panelResult = 'cancelled';
global.wx = {
  getStorageSync: (key) => storage.get(key),
  setStorageSync: (key, value) => storage.set(key, structuredClone(value)),
  removeStorageSync: (key) => storage.delete(key),
  getStorageInfoSync: () => ({ keys: [...storage.keys()] }),
  request(options) {
    const abort = new AbortController();
    void fetch(options.url, {
      method: options.method,
      headers: options.header,
      body: options.data ? JSON.stringify(options.data) : undefined,
      signal: abort.signal,
    })
      .then(async (response) => {
        const raw = await response.text();
        const data = raw ? JSON.parse(raw) : null;
        const pathname = new URL(options.url).pathname;
        requests.push({
          method: options.method,
          pathname,
          key: options.header['Idempotency-Key'],
          data: options.data,
          status: response.status,
        });
        if (
          dropCreationResponse &&
          options.method === 'POST' &&
          pathname.endsWith('/payment-orders') &&
          response.status === 201
        ) {
          dropCreationResponse = false;
          options.fail({ errMsg: 'request:fail response lost after commit' });
        } else {
          options.success({ statusCode: response.status, data });
        }
      })
      .catch(() => options.fail({ errMsg: 'request:fail' }))
      .finally(() => options.complete());
    return { abort: () => abort.abort() };
  },
  requestPayment(options) {
    assert.equal(options.signType, 'RSA');
    assert.match(options.package, /^prepay_id=/);
    assert.ok(options.paySign.length > 20);
    panels.push(panelResult);
    queueMicrotask(() =>
      options.fail({
        errMsg:
          panelResult === 'cancelled'
            ? 'requestPayment:fail cancel'
            : 'requestPayment:fail uncertain SDK result',
      }),
    );
  },
};

const load = (name) => require(path.join(compiled, name));
const { PaymentController } = load('packages/resident/payments/controller.js');
const api = load('packages/resident/payments/api.js');
const billing = load('packages/resident/billing/api.js');
const { residentRequest } = load('auth/resident.js');
const { ApiError } = load('shared/http/client.js');

async function run() {
  let result;
  if (phase === 'create') {
    const bill = await billing.bill(input.billId);
    assert.equal(bill.outstanding_cents, 7000);
    const first = new PaymentController();
    await assert.rejects(
      first.create(bill),
      (error) => error instanceof ApiError && error.code === 'network',
    );
    first.dispose();
    const reopened = new PaymentController();
    const order = await reopened.create(bill);
    assert.equal(order.status, 'pending');
    const creates = requests.filter(
      (item) =>
        item.method === 'POST' && item.pathname.endsWith('/payment-orders'),
    );
    assert.equal(creates.length, 2);
    assert.equal(creates[0].key, creates[1].key);
    assert.deepEqual(creates[0].data, creates[1].data);
    assert.equal(creates[0].status, 201);
    assert.equal(creates[1].status, 201);
    reopened.dispose();
    result = {
      orderId: order.id,
      key: creates[0].key,
      creates: creates.length,
    };
  } else if (phase === 'cancel_close') {
    const bill = await billing.bill(input.billId);
    let controller = new PaymentController();
    let order = await controller.create(bill);
    assert.equal(order.id, input.orderId);
    assert.equal(order.status, 'payable');
    for (const panel of ['cancelled', 'unknown']) {
      panelResult = panel;
      const observed = await controller.pay(order);
      assert.equal(observed.order.id, input.orderId);
      assert.equal(observed.order.status, 'payable');
      assert.equal(observed.order.confirmation_status, 'unconfirmed');
      assert.match(
        observed.message,
        panel === 'cancelled' ? /已取消/ : /正在确认/,
      );
      order = observed.order;
      controller.dispose();
      controller = new PaymentController();
      order = await controller.create(await billing.bill(input.billId));
      assert.equal(order.id, input.orderId);
    }
    const closing = await api.close(order.id);
    assert.equal(closing.status, 'closing');
    assert.equal((await api.order(order.id)).status, 'closing');
    assert.ok(
      requests.every(
        (item) =>
          item.method !== 'POST' || !item.pathname.endsWith('/payment-orders'),
      ),
    );
    assert.equal(
      requests.filter((item) => item.pathname.endsWith('/refreshes')).length,
      2,
    );
    controller.dispose();
    result = { orderId: order.id, panels, status: closing.status };
  } else if (phase === 'release') {
    const closed = await api.order(input.orderId);
    assert.equal(closed.status, 'closed');
    await residentRequest(
      '/miniapp-users/me/house-bindings/' + input.bindingId + '/releases',
      { method: 'POST', data: { expected_row_version: 1 } },
    );
    await assert.rejects(
      billing.bill(input.billId),
      (error) => error instanceof ApiError && error.status === 404,
    );
    const history = await api.order(input.orderId);
    assert.equal(history.status, 'closed');
    assert.deepEqual(history.available_actions, []);
    const controller = new PaymentController();
    assert.equal((await controller.pay(history)).order.id, input.orderId);
    assert.equal(panels.length, 0);
    await assert.rejects(
      api.parameters(input.orderId),
      (error) => error instanceof ApiError && error.status === 404,
    );
    controller.dispose();
    result = { orderId: history.id, status: history.status, billHidden: true };
  } else {
    throw new Error('Unknown integration phase');
  }
  const encoded = JSON.stringify([...storage]);
  assert.ok(!encoded.includes('prepay_id='));
  assert.ok(!encoded.includes('paySign'));
  assert.ok(!encoded.includes('private-prepay'));
  fs.writeFileSync(stateFile, encoded);
  process.stdout.write(JSON.stringify(result));
}
run().catch((error) => {
  // Never print request headers, stored credentials, or payment parameters.
  process.stderr.write(error.stack || error.message);
  process.exitCode = 1;
});
