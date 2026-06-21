// Clearly-fake placeholder identity used to fill out supplier quote/order forms
// for a DEMO. Nothing is ever submitted — these values just populate the fields
// so the form looks complete with the real RFQ text dropped into the notes box.
// Override any field via env (MOCK_APPLICANT_*) if you want.

function env(name: string, fallback: string): string {
  const v = process.env[name]?.trim();
  return v && v.length > 0 ? v : fallback;
}

export type MockApplicant = {
  fullName: string;
  firstName: string;
  lastName: string;
  email: string;
  company: string;
  phone: string;
  address1: string;
  address2: string;
  city: string;
  state: string;
  zip: string;
  country: string;
};

export function getMockApplicant(): MockApplicant {
  return {
    fullName: env("MOCK_APPLICANT_NAME", "Test Engineer"),
    firstName: env("MOCK_APPLICANT_FIRST", "Test"),
    lastName: env("MOCK_APPLICANT_LAST", "Engineer"),
    email: env("MOCK_APPLICANT_EMAIL", "procurement-test@example.com"),
    company: env("MOCK_APPLICANT_COMPANY", "Rocketcursor Test Lab (DEMO — DO NOT SHIP)"),
    phone: env("MOCK_APPLICANT_PHONE", "555-013-0100"),
    address1: env("MOCK_APPLICANT_ADDRESS1", "123 Test Range Road"),
    address2: env("MOCK_APPLICANT_ADDRESS2", "Bay 4"),
    city: env("MOCK_APPLICANT_CITY", "Mojave"),
    state: env("MOCK_APPLICANT_STATE", "CA"),
    zip: env("MOCK_APPLICANT_ZIP", "93501"),
    country: env("MOCK_APPLICANT_COUNTRY", "United States")
  };
}
