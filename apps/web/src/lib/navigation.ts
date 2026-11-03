/** Leaves the app for another page, such as PayPal's. In its own module, so tests can replace it. */
export function goTo(url: string): void {
  window.location.assign(url);
}
