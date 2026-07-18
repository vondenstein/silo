import { Field, FieldError, FieldLabel } from "@/components/ui/field"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useFieldContext } from "@/hooks/form-context"

const NONE = "__none__"

export function SelectField({
  label,
  options,
  placeholder = "—",
  clearable = true,
}: {
  label: string
  options: { value: string; label: string }[]
  placeholder?: string
  clearable?: boolean
}) {
  const field = useFieldContext<string>()
  const isInvalid = field.state.meta.isTouched && !field.state.meta.isValid
  return (
    <Field data-invalid={isInvalid}>
      <FieldLabel htmlFor={field.name}>{label}</FieldLabel>
      <Select
        // Always controlled: "" maps to the NONE sentinel (an unmatched value
        // renders the placeholder), never to undefined/uncontrolled.
        value={field.state.value || NONE}
        onValueChange={(value) => field.handleChange(value === NONE ? "" : value)}
      >
        <SelectTrigger id={field.name} onBlur={field.handleBlur} aria-invalid={isInvalid}>
          <SelectValue placeholder={placeholder} />
        </SelectTrigger>
        <SelectContent>
          {clearable && <SelectItem value={NONE}>None</SelectItem>}
          {options.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {isInvalid && <FieldError errors={field.state.meta.errors} />}
    </Field>
  )
}
