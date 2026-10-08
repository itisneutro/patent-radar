/** Общие классы кнопок: основная (акцентная, со свечением при наведении) и вторичная (контур). */
const BUTTON =
  'inline-flex items-center justify-center gap-2 rounded-full px-5 py-2.5 text-[15px] font-semibold leading-5 transition-[background-color,border-color,color,box-shadow] duration-200 disabled:cursor-not-allowed'

export const buttonPrimary = `${BUTTON} bg-accent text-accent-ink hover:bg-accent-strong hover:shadow-[0_0_28px_var(--c-glow)]`

export const buttonSecondary = `${BUTTON} border border-line-strong text-ink hover:border-accent hover:text-accent disabled:border-line disabled:text-muted disabled:hover:border-line disabled:hover:text-muted`
