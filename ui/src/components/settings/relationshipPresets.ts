export const CUSTOM_RELATIONSHIP_KEY = 'custom'

export interface RelationshipPreset {
  key: string
  label: string
  relationshipLabel: string
  inverseRelationshipLabel: string
}

export const RELATIONSHIP_PRESETS: RelationshipPreset[] = [
  {
    key: 'father_daughter',
    label: 'Father -> daughter',
    relationshipLabel: 'father',
    inverseRelationshipLabel: 'daughter',
  },
  {
    key: 'mother_daughter',
    label: 'Mother -> daughter',
    relationshipLabel: 'mother',
    inverseRelationshipLabel: 'daughter',
  },
  {
    key: 'father_son',
    label: 'Father -> son',
    relationshipLabel: 'father',
    inverseRelationshipLabel: 'son',
  },
  {
    key: 'mother_son',
    label: 'Mother -> son',
    relationshipLabel: 'mother',
    inverseRelationshipLabel: 'son',
  },
  {
    key: 'daughter_father',
    label: 'Daughter -> father',
    relationshipLabel: 'daughter',
    inverseRelationshipLabel: 'father',
  },
  {
    key: 'daughter_mother',
    label: 'Daughter -> mother',
    relationshipLabel: 'daughter',
    inverseRelationshipLabel: 'mother',
  },
  {
    key: 'son_father',
    label: 'Son -> father',
    relationshipLabel: 'son',
    inverseRelationshipLabel: 'father',
  },
  {
    key: 'son_mother',
    label: 'Son -> mother',
    relationshipLabel: 'son',
    inverseRelationshipLabel: 'mother',
  },
  {
    key: 'partner_partner',
    label: 'Partner -> partner',
    relationshipLabel: 'partner',
    inverseRelationshipLabel: 'partner',
  },
  {
    key: 'girlfriend_partner',
    label: 'Girlfriend -> partner',
    relationshipLabel: 'girlfriend',
    inverseRelationshipLabel: 'partner',
  },
  {
    key: 'boyfriend_partner',
    label: 'Boyfriend -> partner',
    relationshipLabel: 'boyfriend',
    inverseRelationshipLabel: 'partner',
  },
  {
    key: 'guardian_child',
    label: 'Guardian -> child',
    relationshipLabel: 'guardian',
    inverseRelationshipLabel: 'child',
  },
]

export function getRelationshipPreset(key: string) {
  return RELATIONSHIP_PRESETS.find(preset => preset.key === key)
}
