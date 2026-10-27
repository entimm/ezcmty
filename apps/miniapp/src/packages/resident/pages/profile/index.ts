import { residentTabs } from '../../navigation';
import { requireIdentity as requireResidentIdentity } from '../../../../core/identities';
import { BUILD_VERSION } from '../../../../config';
import * as account from '../../../../core/account-api';
import {
  currentCredential,
  logout,
  sessionRevision,
} from '../../../../core/session';
import { errorText } from '../../../../core/request';
import { go } from '../../../../ui/navigation';
import { PageScope } from '../../page-state';
import { loadAll } from '../../presentation';
Page({
  data: {
    tabs: residentTabs,
    version: BUILD_VERSION,
    signed: false,
    phoneCount: 0,
    phoneError: '',
    sheet: '',
    busy: false,
    error: '',
  },
  visible: false,
  lifetime: 0,
  scope: null as unknown as PageScope,
  onLoad() {
    this.scope = new PageScope();
    this.scope.watch(() =>
      this.setData({
        signed: false,
        phoneCount: 0,
        phoneError: '',
        sheet: '',
        busy: false,
        error: '',
      }),
    );
  },
  onShow() {
    this.visible = true;
    this.lifetime++;
    if (
      currentCredential() &&
      !requireResidentIdentity(
        'resident',
        '/packages/resident/pages/profile/index',
      )
    )
      return;
    const signed = !!currentCredential();
    if (!this.scope.enter()) this.setData({ phoneCount: 0, phoneError: '' });
    this.setData({ signed, busy: false, sheet: '', error: '' });
    if (signed) void this.loadPhones();
  },
  onHide() {
    this.visible = false;
    this.lifetime++;
    this.scope.leave();
    this.setData({ sheet: '' });
  },
  onUnload() {
    this.visible = false;
    this.lifetime++;
    this.scope.dispose();
  },
  async loadPhones() {
    const valid = this.scope.next();
    try {
      const phones = await loadAll((page) => account.listPhones(page));
      if (valid())
        this.setData({
          phoneCount: phones.filter((phone) => phone.status === 'active')
            .length,
          phoneError: '',
        });
    } catch (error) {
      if (valid()) this.setData({ phoneError: errorText(error) });
    }
  },
  houses() {
    go('houses');
  },
  orders() {
    go('payment-orders');
  },
  claims() {
    go('claims');
  },
  phones() {
    go('phones');
  },
  login() {
    go('login');
  },
  help() {
    this.setData({ sheet: 'help' });
  },
  about() {
    this.setData({ sheet: 'about' });
  },
  exit() {
    this.setData({ sheet: 'logout', error: '' });
  },
  close() {
    if (!this.data.busy) this.setData({ sheet: '' });
  },
  identities() {
    go('identities');
  },
  async confirm() {
    if (!this.visible) return;
    const lifetime = this.lifetime;
    const session = sessionRevision();
    if (this.data.sheet !== 'logout') {
      this.close();
      return;
    }
    if (this.data.busy) return;
    this.setData({ busy: true, error: '' });
    try {
      await logout();
    } catch {
      /* Local session is cleared even if remote revocation could not be confirmed. */
    }
    if (
      !this.visible ||
      lifetime !== this.lifetime ||
      currentCredential() ||
      sessionRevision() > session + 1
    )
      return;
    this.setData({ sheet: '', signed: false, phoneCount: 0, busy: false });
    go('home');
  },
});
