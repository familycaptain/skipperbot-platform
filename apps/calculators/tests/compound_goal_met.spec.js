// Box-2 acceptance for calculators.compound-interest.goal-already-met
//
// The Compound-interest tab must never show a negative duration/rate when the
// goal (Future value) is at or below the current balance (Principal). It shows a
// neutral "already met" note instead, and still computes a real positive figure
// when the goal is above the balance.
//
// Runs on box 2 against the live web app (Playwright is not installed on box 1).
import { test, expect } from "@playwright/test";

const APP_URL = process.env.SKIPPER_WEB_URL || "http://localhost:5173";

async function openCompoundTab(page) {
  await page.goto(APP_URL);
  // Open the Calculators app, then the Compound interest tab.
  await page.getByRole("button", { name: /Compound interest/i }).click();
}

async function fill(page, label, value) {
  // Each Field renders a <label> with the text and an <input> inside it.
  const field = page.locator("label", { hasText: label }).locator("input");
  await field.fill(value);
}

test("goal below current balance shows 'already met', not a negative duration", async ({ page }) => {
  await openCompoundTab(page);
  await fill(page, "Principal", "20000");
  await fill(page, "Future value", "8408");
  await fill(page, "Years", ""); // leave blank to solve for Years
  await page.getByRole("button", { name: /^Calculate$/ }).click();

  const result = page.locator("text=/already reached it/i");
  await expect(result).toBeVisible();
  // No negative number anywhere in the result region.
  await expect(page.locator("text=/-\\d/")).toHaveCount(0);
});

test("goal equal to current balance shows 0 years", async ({ page }) => {
  await openCompoundTab(page);
  await fill(page, "Principal", "10000");
  await fill(page, "Future value", "10000");
  await fill(page, "Years", "");
  await page.getByRole("button", { name: /^Calculate$/ }).click();

  await expect(page.getByText(/^0 yr$/)).toBeVisible();
  await expect(page.locator("text=/-\\d/")).toHaveCount(0);
});

test("goal above current balance still computes a positive number of years", async ({ page }) => {
  await openCompoundTab(page);
  await fill(page, "Principal", "10000");
  await fill(page, "Future value", "20000");
  await fill(page, "Years", "");
  await page.getByRole("button", { name: /^Calculate$/ }).click();

  // A positive "<n> yr" result, never negative.
  await expect(page.getByText(/\b\d+(\.\d+)?\s*yr\b/)).toBeVisible();
  await expect(page.locator("text=/-\\d/")).toHaveCount(0);
});
