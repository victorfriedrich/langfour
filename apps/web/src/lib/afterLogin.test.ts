import { beforeEach, expect, it } from 'vitest';
import { peekAfterLogin, rememberAfterLogin, takeAfterLogin } from './afterLogin';

beforeEach(() => localStorage.clear());

it('lets the original login tab resume without consuming the callback destination', () => {
  const path = '/oauth/consent?authorization_id=test';
  rememberAfterLogin(path);
  expect(peekAfterLogin()).toBe(path);
  expect(takeAfterLogin()).toBe(path);
  expect(takeAfterLogin()).toBe('/');
});

it.each(['https://evil.example', '//evil.example', '/\\evil.example'])('refuses external destination %s', path => {
  rememberAfterLogin(path);
  expect(takeAfterLogin()).toBe('/');
});
