import { createFormHook } from "@tanstack/react-form"

import { DateField } from "@/components/form/date-field"
import { SelectField } from "@/components/form/select-field"
import { SubmitButton } from "@/components/form/submit-button"
import { TextField } from "@/components/form/text-field"
import { TextareaField } from "@/components/form/textarea-field"
import { fieldContext, formContext } from "@/hooks/form-context"

export const { useAppForm } = createFormHook({
  fieldContext,
  formContext,
  fieldComponents: { TextField, TextareaField, SelectField, DateField },
  formComponents: { SubmitButton },
})
