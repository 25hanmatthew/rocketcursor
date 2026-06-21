import { z } from "zod";

export const MaterialRequirementSchema = z.object({
  item: z.string(),
  quantity: z.number().int().positive(),
  requirements: z.record(z.string(), z.any())
});

export const ProcurementInputSchema = z.object({
  projectName: z.string().default("Rocketcursor procurement run"),
  designPath: z.string().optional(),
  reportPath: z.string().optional(),
  materials: z.array(MaterialRequirementSchema)
});

export const SupplierCandidateSchema = z.object({
  item: z.string(),
  supplier: z.string(),
  productName: z.string(),
  partNumber: z.string().nullable(),
  productUrl: z.string(),
  price: z.string().nullable(),
  leadTime: z.string().nullable(),

  // Engineering-relevant extracted fields.
  pressure_rating_pa: z.number().nullable(),
  volume_l: z.number().nullable(),
  minimum_cda_m2: z.number().nullable(),
  fluid_compatibility: z.array(z.string()).default([]),
  oxygen_clean: z.boolean().nullable(),
  cryogenic_compatible: z.boolean().nullable(),

  // Requirement comparison fields.
  matched_requirements: z.array(z.string()).default([]),
  missing_requirements: z.array(z.string()).default([]),
  failed_requirements: z.array(z.string()).default([]),

  confidence: z.number().min(0).max(1),
  notes: z.string(),

  // Portal quote submission fields (populated after approval-gated quote step).
  quoteStatus: z
    .enum(["not_requested", "draft", "submitted", "pending_review", "failed"])
    .optional(),
  quoteConfirmation: z.string().nullable().optional(),
  quotedPrice: z.string().nullable().optional(),
  quotedLeadTime: z.string().nullable().optional()
});

export const QuoteConfirmationSchema = z.object({
  confirmationNumber: z.string().nullable().optional(),
  quotedPrice: z.string().nullable().optional(),
  quotedLeadTime: z.string().nullable().optional(),
  quoteStatus: z.enum(["draft", "submitted", "pending_review"]).optional()
});

export const BOMSchema = z.object({
  generatedAt: z.string(),
  projectName: z.string(),
  items: z.array(
    z.object({
      item: z.string(),
      quantity: z.number(),
      requirements: z.record(z.string(), z.any()),
      candidates: z.array(SupplierCandidateSchema)
    })
  ),
  approvalRequired: z.boolean().default(true),
  sent: z.boolean().default(false)
});

export type ProcurementInput = z.infer<typeof ProcurementInputSchema>;
export type SupplierCandidate = z.infer<typeof SupplierCandidateSchema>;
export type QuoteConfirmation = z.infer<typeof QuoteConfirmationSchema>;
export type BOM = z.infer<typeof BOMSchema>;