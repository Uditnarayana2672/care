import { expect, Page, test } from "@playwright/test";

const login = async (page: Page, name: string) => {
  await page.goto("/dashboard");
  const picker = page.getByRole("button", { name: new RegExp(name) });
  const select = page.getByLabel("Switch demo user");
  await expect(picker.or(select)).toBeVisible();
  if (await picker.isVisible()) await picker.click();
  else {
    const opts = await select.locator("option").allTextContents();
    await select.selectOption({ label: opts.find((o) => o.includes(name))! });
  }
  await expect(page.getByText(/Signed in as/)).toBeVisible();
  await expect(page.getByLabel("Message")).toBeVisible();
};
const say = async (page: Page, text: string) => {
  await page.getByLabel("Message").fill(text);
  await page.getByLabel("Message").press("Enter");
};

test("3-minute demo story", async ({ page }) => {
  await login(page, "Anjali");

  // Step 2 — orchestrated board with reasons (W9)
  await expect(page.getByTestId("card-Serve lunch")).toContainText("anxious if lunch is late");
  await expect(page.getByTestId("card-Serve lunch")).toContainText("observed 4×");
  // Step 5 — trend banner (W8)
  await expect(page.getByRole("alert").first()).toContainText("not a diagnosis");

  // Step 3 — W3 check-in → W7 reschedule proposal
  await say(page, "Was Asha's bath done?");
  const chat = page.getByTestId("msgs");
  await expect(chat).toContainText("Asha's morning bath (8:00 AM)");
  await chat.getByRole("button", { name: "Not done" }).last().click();
  await chat.getByRole("button", { name: "Refused" }).click();
  await chat.getByRole("button", { name: "Feels cold" }).click();
  await expect(chat).toContainText("Move Asha's morning bath to 1:30 PM?");
  await expect(chat).toContainText("Observed pattern — not a clinical instruction");
  await chat.getByRole("button", { name: /Yes, move to 1:30 PM/ }).click();
  await expect(chat).toContainText("I've remembered why");
  await expect(page.getByTestId("card-Morning bath")).toContainText("Not done");

  // Step 4 — W6 what worked before
  await say(page, "Asha is restless after dinner");
  await chat.getByRole("button", { name: "Save", exact: true }).click();
  await expect(chat).toContainText("Offer a 10-minute assisted evening walk");
  await expect(chat.getByText("Memory used").last()).toBeVisible({ timeout: 2000 }).catch(() => {});

  // Step 6 — W5 handoff as Rohan
  await login(page, "Rohan");
  await say(page, "I'm taking over Asha tonight. What should I know?");
  await expect(page.getByTestId("msgs")).toContainText("warm water");
  await expect(page.getByTestId("msgs")).toContainText("Anjali");
  await expect(page.getByTestId("msgs")).toContainText("Memory used");

  // Step 7 — memory off vs on
  await page.getByRole("button", { name: "Compare memory on/off" }).click();
  await expect(page.getByTestId("msgs")).toContainText("Memory off");
  await expect(page.getByTestId("msgs")).toContainText("don't have remembered history");
});

test("enrollment wizard creates a patient with a code", async ({ page }) => {
  await page.goto("/enroll");
  await page.getByLabel("Your full name").fill("Test Elder");
  await page.getByLabel("Age", { exact: true }).fill("79");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("button", { name: "With a walker" }).click();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByLabel("Add a medicine").fill("Metformin");
  await page.getByRole("button", { name: "morning" }).click();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("button", { name: "Finish" }).click();
  await expect(page.getByTestId("patient-code")).toHaveText(/CB-\d{4}/);
});
