# CPQ Native-UI Layout Visibility — Plan

Separate from `docs/CPQ_RULE_TOOL_FLOW_PLAN.md` (which covers rule
extraction/evaluation and payload correctness) — this plan covers a
DIFFERENT question: which attributes the real BigMachines/Oracle CPQ UI
actually displays on screen, and how `CpqEngine` should determine the same
set, including catalogs that don't carry the mechanism this plan is built
around.

## 1. Native UI layout visibility — a THIRD, unread rule mechanism

Checked why the real BigMachines UI shows only a subset of attributes on
screen (user-supplied screenshot) while the JSON payload carries all 427.
`CpqEngine` currently decides visibility using only `hidden`/`required`
flags + hiding/constraint/recommendation rules — it has never read
`bm_config_layout_attr_assoc`, `bm_layout_model`, or `rule_type=6` rules at
all.

**Confirmed mechanism (checked against the raw XML, not assumed):**
- Every screenshot attribute (`ultimateDestinationCountry`, `hWVersion_astro`,
  `productSelectionProduct_all`, `softwareBundlesBundleType_astro`,
  `packageTypeBundles_astro`, `isProvisioningRequiredInCloudEnv_astro`,
  `solutionTypeDevices_astro`) has 2-3 rows in `bm_config_layout_attr_assoc`,
  ALL referencing the same rule_id set: `22194396138` / `19435387689` /
  `22194396144` — all three are `bm_config_rule` entries with
  **`rule_type=6`**, named **"Configuration Flow For Astro Devices
  (Portable)"** (+ a "_sysConfig" variant).
- `rule_type=6` is a **third rule category** — a flow/page-membership gate,
  distinct from hiding(11)/constraint/recommendation(1,2,23).
  `layout_model_id`→`layout_id`/`parent_id`/`order_number` also encodes a
  real page/section/field hierarchy with actual display order.
- 350/427 APX Next attrs (82%) have SOME layout placement; 77 (18%) have
  none — those are pure backend/computation-only fields, never shown on any
  page by design.
- **Confirmed generic, not APX-specific**: an independent second file
  (`SVX Video Remote Speaker Microphone.xml`) shows the identical pattern —
  2 `rule_type=6` rules ("Configuration Flow For vX650 (Video
  Solutions_BOM)" + "_SysConfig"), and those two rule_ids are literally the
  top 2 most-referenced rule_ids across ALL `layout_attr_assoc` rows (133
  each = 100% of 266 total). 137/235 attrs (58%) have layout placement, 98
  (42%) don't.

**Gap**: without reading this, Aryx's `ask` flow can surface attributes the
real native UI would never show for this device class (wrong flow/page),
and has no sense of real display grouping or order.

## 2. Fallback plan — catalogs with NO Configuration-Flow rule

Two confirmed catalogs both have `rule_type=6` flow rules, but a third
ingested catalog might not (older export, different BM configuration
style, or a source that never used this convention). The fix must not
assume `rule_type=6` is universal — it must degrade gracefully, never show
zero attributes, and never crash.

**Three tiers, tried in order, each a strictly-decreasing-confidence
fallback — not "flow rule or nothing":**

| Tier | Signal | Behavior |
|---|---|---|
| **1 (primary)** | `rule_type=6` rules exist AND are referenced by `bm_config_layout_attr_assoc` | Scope attrs to those referenced by the catalog's flow rule(s); use `layout_model_id`'s `order_number`/`parent_id` for real display order/grouping. Confirmed working on 2 independent catalogs. |
| **2 (structural fallback)** | No `rule_type=6` flow rule, but `bm_config_layout_attr_assoc`/`bm_layout_model` still exist | Scope attrs to whatever has ANY layout placement (regardless of which rule references it, if any), ordered by `order_number` — still real UI-truth, just without flow-specific grouping/naming. |
| **3 (safety net)** | No layout data at all for this catalog | Fall back to `load_product_config`'s CURRENT, already-shipped behavior (hidden/required flags + hiding/constraint/recommendation rules) — zero new code needed here; this tier is free. |

**Detection, not per-attribute guessing**: run ONE cheap existence check
per `catalog_prefix` (e.g. `EXISTS(rule_type=6 rows)` /
`EXISTS(layout_attr_assoc rows)`), cache it the same way
`_FLAG_KEYWORD_INDEX_CACHE`/`_SHARED_SCRIPT_CACHE` already cache other
per-catalog signals — never re-checked per attribute, never per turn.

**Never silently drop to a worse tier mid-conversation**: the tier is
decided once when the catalog is first scoped (same point `catalog_prefix`
is resolved today) and stays fixed for that catalog for the process
lifetime, same caching lifetime as the other per-catalog signals.

**Explicitly NOT in scope for this fallback**: guessing which attrs to show
when NONE of the three signals exist and even `required`/`hidden` flags are
absent — that catalog genuinely has no UI-visibility signal at all, and the
existing "ask" default (show everything not explicitly hidden) is the
correct, D2-consistent behavior, not a gap to close further.

---

## 3. Full attribute list under Configuration-Flow rules (both catalogs)

### APX Next — 350 attributes under 'Configuration Flow For Astro Devices (Portable)' (+ _sysConfig)

1. `AccessoriesQuantityDummyArrayAttribute_astro`
2. `_BM_USER_GROUPS`
3. `_bm_model_description`
4. `_bm_model_modelNumber`
5. `_bm_model_name`
6. `_bm_model_orderingGuide`
7. `_bm_model_partner_organization_id`
8. `_bm_model_partner_part_id`
9. `_bm_model_productInformationURL`
10. `_bm_model_variable_name`
11. `_bm_pline_name`
12. `_bm_pline_variable_name`
13. `aSTROSystemID_astro`
14. `aTAKEnabledPackage_astro`
15. `aTAKNonPromoApplicationServices_astro`
16. `accessoriesHelpText_all`
17. `accessoriesPreviousValue_astro`
18. `accessoriesSolutionCategoryHelpText_astro`
19. `accessoriesSolutionSet_astro`
20. `addToQuoteFLag`
21. `addVX650VideoWirelessRemoteSpeakerMicrophone_astro`
22. `additionalApplicationServicesMonths_astro`
23. `additionalApplicationServices_astro`
24. `additionalSystemEnhancementFeatureType_astro`
25. `advancedSystemKeyHardwareKey_astro`
26. `advancedSystemKeySWKEYSUPPLEMENTALDATA_astro`
27. `agencyDomainNameID_astro`
28. `agencyHasMotorolaEvidenceSolution_astro`
29. `antennasType_astro`
30. `anywhereProgramming_astro`
31. `appServicePromoFlag_astro`
32. `applicationServicePromoHelptext_astro`
33. `applicationServicePromotionalDuration_astro`
34. `applicationServicesDurationYears_astro`
35. `applicationServicesHelpText1_astro`
36. `applicationServicesIntroBundle_astro`
37. `applicationServicesSelection_astro`
38. `applicationServices_astro`
39. `bOMDisplaytb_astroBOM`
40. `bOMEnabledModel`
41. `bOMOptimizeFlag_astroBOM`
42. `backToPackage`
43. `backupPTT_astro`
44. `bandClassType_astro`
45. `baselineReleaseSWHelpText_astro`
46. `baselineReleaseSW_astro`
47. `batteryIncludeaSpare_astro`
48. `batteryQuantityforSparesDummy_astro`
49. `batteryQuantityforSpares_astro`
50. `batteryType_astro`
51. `bcTestTrigger_astro`
52. `beltClipType_astro`
53. `bulkAddFlag`
54. `bulkAddSSPLValues`
55. `cBPQRCode_astro`
56. `cableDataCable_astro`
57. `carrierSelectionMultiSelect_astro`
58. `carryCaseHelpText_astro`
59. `ccAdminIdRadioCentral_astro`
60. `ccArrayControl_astro`
61. `checkProvAgencises_astro`
62. `clearPackageJson`
63. `clearPkgJsonFlag`
64. `commandCentralIdExists_astro`
65. `commandCentral_Id_atsro`
66. `commandCentral_ato_atsro`
67. `commerceAttrOverride`
68. `commerceAttrs`
69. `configAction_all`
70. `configProcessStepHTML_all`
71. `configurationRuleRunOnceCount_astro`
72. `contractSearchString`
73. `contractsInternalIDNumber`
74. `contractsRevision`
75. `currentCounterForNonMandatoryParts`
76. `customerContextJson`
77. `customerName_astro`
78. `customerType`
79. `customerUIN`
80. `dELETELTE_astro`
81. `dHSAssetTagLabel_astro`
82. `dMSDurationYears_astro`
83. `dMSHelpText_astro`
84. `dMSNonpromotionalDurationMonths`
85. `dMSPromotionalDurationMonths_astro`
86. `dataTableList_astro`
87. `defaultAttrValuesMasterString_astro`
88. `descriptionOfEndUser_astro`
89. `deviceManagementTraining_astro`
90. `dmsDuration_astro`
91. `documentationDataLinkManagerSoftwareCD_astro`
92. `documentationTestResultsRatedAudioPrintoutLabel_astro`
93. `durationAttributeName`
94. `dynamicCSS`
95. `eNDUSERMCN_astro`
96. `edit_RecommendedConfiguration_astro`
97. `enableDualActiveSim_astro`
98. `extendRangeTo762764MHz_astro`
99. `fedQRCode_astro`
100. `fedRampHelpText_astro`
101. `firstName_astro`
102. `firstNetEligibility_astro`
103. `formulaTimeStamp_astro`
104. `fourOrMoreApplicationsDiscountHelptext_astro`
105. `fullItemList_astro`
106. `getDataFromCookieFlag`
107. `govVersusNonGovCustomer`
108. `hWVersion_astro`
109. `hidddenRecordSeparator_allFamilly`
110. `hiddenAccesoriesMasterString_astro`
111. `hiddenConstraintMasterStringForBaseModel_astro`
112. `hiddenConstraintMasterString_astro`
113. `hiddenMasterStringForAstroPortable_astro`
114. `hiddenMasterStringForNonFrequencyParametricData_astro`
115. `hiddenMasterStringForRelatedServices_astro`
116. `hiddenModeContract`
117. `hiddenModePackage`
118. `hiddenRowSeparator_allFamily`
119. `hiddenSeriesModelsMasterString_all`
120. `hiddenUISequenceForModelSelection_astro`
121. `hiddenUISequenceMasterString_astro`
122. `hideUDCCFlag_all`
123. `holdDetail_astro`
124. `hqSkuLabel_astro`
125. `html_To_ForcedSet_RecommendedConfiguration_astro`
126. `includeAccidentalDamageAddDMSCoverage_astro`
127. `internalOptionsFlag_astro`
128. `internaloptionFlag10`
129. `internaloptionFlag3`
130. `isAdditionalApplicationServicesMonthsGreaterThan0`
131. `isAdditionalApplicationServicesMonthsLessThan25_astro`
132. `isCustomerTypeFEDERAL_astro`
133. `isDMSNonPromotionalDurationMonthsLessThan61_astro`
134. `isDMSNonpromotionalDurationMonthsThan0_astro`
135. `isDMSNonpromotionalDurationMonthsThan37_astro`
136. `isDMSPromotionalDurationMonthsThan11_astro`
137. `isDMSPromotionalDurationMonthsThan37_astro`
138. `isFeatureTypeDELETEBLUETOOTH_astro`
139. `isFeatureTypeDELETEGPSACTIVATION_astro`
140. `isFeatureTypeDELETEINTEGRATEDVOICEANDDATA_astro`
141. `isFeatureTypeDELETENARROWBANDINGWAIVERREQUIRED_astro`
142. `isFeatureTypeIsDELETEMISSIONCRITICALBLUETOOTH_astro`
143. `isFeatureTypeIsDELETENARROWBANDINGWAIVERREQUIRED_astro`
144. `isFedRampRequired_astro`
145. `isItemType2WireSurveillanceKitForSVXVideoRSM_astro`
146. `isItemTypeCOILEDTETHERLANYARDSETOF5_astro`
147. `isItemTypeEARPIECELARGELEFT_astro`
148. `isItemTypeEARPIECELARGERIGHT_astro`
149. `isItemTypeEARPIECEMEDIUMLEFT_astro`
150. `isItemTypeEARPIECEMEDIUMRIGHT_astro`
151. `isItemTypeEARPIECESMALLLEFT_astro`
152. `isItemTypeEARPIECESMALLRIGHT_astro`
153. `isItemTypeReceiveOnlyEarpieceForSVXVideoRSM_astro`
154. `isItemTypeSVX12SlotBatteryOnlyCharger_astro`
155. `isItemTypeSVXChargeAndUploadSmartDock_astro`
156. `isItemTypeSVXVideoRSMSpareBattery_astro`
157. `isMultikeyTypeOTARWITHMULTIKEY_astro`
158. `isPackageTypeBundlesENCRYPTIONBUNDLELACR_astro`
159. `isPackageTypeBundlesSECURITYBUNDLEREV1_astro`
160. `isParametricDataApplicable_astro`
161. `isProvisioningRequiredInCloudEnvHelpText_astro`
162. `isProvisioningRequiredInCloudEnvYES_astro`
163. `isProvisioningRequiredInCloudEnv_astro`
164. `isQuantityOf2WireSurveillanceKitForSVXVideoRSMGreaterThan0_astro`
165. `isQuantityOfCOILEDTETHERLANYARDSETOF50_astro`
166. `isQuantityOfEARPIECELARGELEFT0_astro`
167. `isQuantityOfEARPIECELARGERIGHTgreaterThan0_astro`
168. `isQuantityOfEARPIECEMEDIUMLEFT0_astro`
169. `isQuantityOfEARPIECEMEDIUMRIGHT0_astro`
170. `isQuantityOfEARPIECESMALLLEFT0_astro`
171. `isQuantityOfEARPIECESMALLRIGHT0_astro`
172. `isQuantityOfReceiveOnlyEarpieceForSVXVideoRSMGreaterThan0_astro`
173. `isQuantityOfSVX12SlotBatteryOnlyChargerDrivesGreaterThan0_astro`
174. `isQuantityOfSVXChargeAndUploadSmartDockGreaterthan0_astro`
175. `isQuantityOfSVXVideoRSMSpareBatteryGreaterThan0_astro`
176. `isQuantityVX650ItemTypeThan0_astro`
177. `isRelatedServiceCategoryAryDEVICEPROGRAMMING_astro`
178. `isSoftwareBundlesSECURITYBUNDLE_astro`
179. `isThisASPARERadioAntenna_astro`
180. `isThisASPARERadioBatt_astro`
181. `isUltimateDestinationCountryCA_astro`
182. `itemTypeVX650_astro`
183. `languageLanguageType_astro`
184. `lastName_astro`
185. `locationOnboarding_astro`
186. `manual_astro`
187. `mergePackage`
188. `modelSelectionDisplayType_astro`
189. `modelSelectionFrequencyBandMslDummy1_astro`
190. `modelSelectionFrequencyBandMslDummy2_astro`
191. `modelSelectionFrequencyBandMslDummy3_astro`
192. `modelSelectionFrequencyBandMsl_astro`
193. `modelSelectionFrequencyBandPlus_astro`
194. `modelSelectionFrequencyBands_astro`
195. `modelSelectionHazardousLocation_astro`
196. `modelSelectionHousing_astro`
197. `modelSelectionKeypadType_astro`
198. `modelSelectionKnobType_astro`
199. `modelSelectionOrderType_astro`
200. `modelSelectionPrimaryFrequency_astro`
201. `modelSelectionRegion_astro`
202. `modelSelectionRuggedizedHousing_astro`
203. `modelSelectionSecondaryFrequency_astro`
204. `modelSelectionSubmersibleDeltaT_astro`
205. `modelSelectionbaseModel_astro`
206. `modelSelectionmadeInAmerica`
207. `modelname_all`
208. `msEnableDualBandOperation_astro`
209. `multikeyType_astro`
210. `nSBomFlag`
211. `nonFrequencyParametricData`
212. `nonFrequencyParametricData_astro`
213. `nonMandatoryPartsListString_all`
214. `numberOfSeatsDummy_astro`
215. `numberOfSeats_astro`
216. `operationModeType_astro`
217. `paIdExists_astro`
218. `packageAccessoriesString`
219. `packageChoiceString`
220. `packageConfigState`
221. `packageCpqModel`
222. `packageHtmlData`
223. `packageIDNumber_contracts`
224. `packageInvokedFlag`
225. `packageJsonData`
226. `packageName`
227. `packageNumber`
228. `packagePriceBook`
229. `packageProductFamily`
230. `packageProductLine`
231. `packageRegion`
232. `packageRevision`
233. `packageStatus`
234. `packageType`
235. `packageTypeBundles_astro`
236. `packageTypeHelpText_astro`
237. `packages_astro`
238. `packingPackageType_astro`
239. `preSalesEnggAcknowledgement_astro`
240. `previousCounterForNonMandatoryParts_astro`
241. `previousValueStrings_astro`
242. `pricingPkgDetails`
243. `productInformationText_astro`
244. `productSelectionHelptext_astro`
245. `productSelectionProduct_all`
246. `promoApplicationServices_astro`
247. `promotionArrayController`
248. `promotionDataString`
249. `promotionExist`
250. `promotionId`
251. `promotionMessage`
252. `promotionOptOut`
253. `promotionPricingInstructions`
254. `provAgenArrayControl_astro`
255. `provAgencyCC_IdJSON_astro`
256. `provAgencyDummy`
257. `provAgencyId_astro`
258. `provAgencyJSON_astro`
259. `provAgencyName_astro`
260. `provAgencyType_astro`
261. `provisioningAgencyRadioManagement_astro`
262. `provisioningAssistance_astro`
263. `qtyOf12pinInterfaceto10PinRFDCAdaptor_astro`
264. `qtyOfVX650RemoteSpeakerMicDummy_astro`
265. `qtyOfVX650RemoteSpeakerMic_astro`
266. `qtyOfXVN500RemoteSpeakerMicDummy_astro`
267. `qtyOfXVN500RemoteSpeakerMic_astro`
268. `quantityVX650ItemType_astro`
269. `quickStartGuide_astro`
270. `rFIDRFIDEquipped_astro`
271. `rSMDMSDuration_astro`
272. `rSMDMSHelptext_astro`
273. `rSMType_astro`
274. `radioCentralProvisioningAgencyStatus_astro`
275. `radioCentralSmartprogrammingHelptext_astro`
276. `relatedServiceCategoryAry_astro`
277. `relatedServiceCategory_astro`
278. `relatedServiceDescriptionAry_astro`
279. `relatedServicePartsAry_astro`
280. `relatedServiceQuantityAry_astro`
281. `relatedServiceSelectAry_astro`
282. `relatedServicesPreviousValues_astro`
283. `relatedServicesType_astro`
284. `relatedSoftwareAndServiceArrayControl_astro`
285. `requireForRadioFEDFCCTriggerSS_astro`
286. `retrieveProvAgenciesAndCCIds_astro`
287. `sIFormulaVersion_astro`
288. `sIMCardSelection_astro`
289. `sME_EBSFlag`
290. `sMP3_1_CONFIG_FLAG`
291. `salesApprover_astro`
292. `salesContactEmailAddress_astro`
293. `salesContactNameForThisOrder_astro`
294. `saveChanges_RecommendedConfiguration_astro`
295. `secureEncryptionType_astro`
296. `selectCommandCentral_ID_astro`
297. `selectEndUserType_astro`
298. `selectProvAgencySSPL_astro`
299. `selectSecondarySIMCard_astro`
300. `serviceActivationDelay_astro`
301. `serviceBatteryRefreshService_astro`
302. `serviceDuration_astro`
303. `serviceNoteSOWGuideText_astro`
304. `serviceNoteSOW_astro`
305. `serviceTypeAdditionalDMSCoverage_astro`
306. `serviceTypeRSM_astro`
307. `serviceType_astro`
308. `sessionVariable_TER`
309. `smartDockHelptext_astro`
310. `smartIncidentHelpText_astro`
311. `smartInsight_astro`
312. `smartLocateHelpText_astro`
313. `smartMessagingHelpText_astro`
314. `smartvideoHelpText_astro`
315. `softwareBundleHelpText_astro`
316. `softwareBundlesBundleType_astro`
317. `solutionCategoryArrayControl_astro`
318. `solutionCategoryDescription_astro`
319. `solutionCategoryListPrice_astro`
320. `solutionCategoryParts_astro`
321. `solutionCategoryPriceValidity_astro`
322. `solutionCategoryQuantity_astro`
323. `solutionCategory_astro`
324. `solutionTypeDevices_astro`
325. `solutionTypeDuration_astro`
326. `spSurveillancePackagesType_astro`
327. `spSurveillancePackagesTypes_astro`
328. `subscriptionBillingAddDMSCoverage_astro`
329. `subscriptionEndDate`
330. `subscriptionStartDate`
331. `systemEnggAttributeValueString_astro`
332. `systemEnhancementFeatureType_astro`
333. `systemID_astro`
334. `tAACompliant_astro`
335. `technicalContactEmailAddress_astro`
336. `trainTheTrainerTraining_astro`
337. `trainingCostFactorMasterString_astro`
338. `uDCCOverrideWarningHelpText`
339. `ultimateDestinationCountry`
340. `update`
341. `vX650ItemTypeArrayControl_astro`
342. `validationOrg`
343. `videoAdminEmailAddress_astro`
344. `videoAdminPhoneNumber_astro`
345. `videoRSMDeviceManagementDuration_astro`
346. `videoRSM_astro`
347. `viqiSmartappText_astro`
348. `virtualPartner_astro`
349. `vx650PartsArray`
350. `wirelessCarrier_astro`

### SVX Video RSM — 137 attributes under 'Configuration Flow For vX650 (Video Solutions_BOM)' (+ _SysConfig)

1. `Accessories2Quantity_viSoln`
2. `AccessoriesQuantityDummyArrayAttribute_viSoln`
3. `AccessorietoQuantityDummyArrayAttribute_viSoln`
4. `MountingQuantityDummyArrayAttribute_viSoln`
5. `_BM_USER_GROUPS`
6. `_BM_USER_LOGIN`
7. `_bm_model_description`
8. `_bm_model_imageURL`
9. `_bm_model_name`
10. `_bm_model_orderingGuide`
11. `_bm_model_productInformationURL`
12. `_bm_model_variable_name`
13. `_bm_pline_variable_name`
14. `accecsssoriesQuantityArray_viSoln`
15. `accecsssoriesQuantityArraydummy_viSoln`
16. `accesoriesType2ArrayControl_viSoln`
17. `accessoriesArrayControlAttribute_viSoln`
18. `accessoriesDescriptionArray_viSoln`
19. `accessoriesListPriceArray_viSoln`
20. `accessoriesPartsArray_viSoln`
21. `accessoriesPreviousValue_viSoln`
22. `accessoriesPriceValidityArray_viSoln`
23. `accessoriesSolutionCategoryArray_viSoln`
24. `accessoriesSolutionSet_viSoln`
25. `accessoryType2SelectType_viSoln`
26. `activeRenewalMergeDate_viSoln`
27. `adminEmailAddress_viSoln`
28. `adminPhoneNumber_viSoln`
29. `adminUserName_viSoln`
30. `agencyDomainName_ID_viSoln`
31. `archTypeSubDuration_viSoln`
32. `archeTypeHelpText_viSoln`
33. `archeType_viSoln`
34. `bOMDisplayTab`
35. `bOMEnabledModel`
36. `bWCNumberOfRefreshes_viSoln`
37. `billingOptions_viSoln`
38. `bulkAddFlag`
39. `bulkAddSSPLValues`
40. `cancelFlag`
41. `cancelFlagMessage`
42. `ciSubscriptionEndDate_viSoln`
43. `ciSubscriptionStartDate_viSoln`
44. `commerceAttrOverride`
45. `commerceAttrs`
46. `configAction_all`
47. `configProcessStepHTML_all`
48. `configurationRuleRunOnceCount_viSoln`
49. `currentCounterForNonMandatoryParts`
50. `customerContextJson`
51. `customerType`
52. `customerUIN`
53. `dMSDuration_viSoln`
54. `dataTableList_viSoln`
55. `deviceManagementDuration_viSoln`
56. `deviceManagementOnly_viSoln`
57. `durationAttributeName`
58. `dynamicCSS`
59. `edit_RecommendedConfiguration_viSoln`
60. `entitlementEmailAddress_viSoln`
61. `evidenceManagementHelpText_viSoln`
62. `formulaTimeStamp_viSoln`
63. `hidddenRecordSeparator_allFamilly`
64. `hiddenAccesoriesMasterString_viSoln`
65. `hiddenConstraintMasterStringForBaseModel_viSoln`
66. `hiddenConstraintMasterString_viSoln`
67. `hiddenDefaultAttrValuesMasterString_viSoln`
68. `hiddenRowSeparator_allFamily`
69. `hiddenSeriesModelsMasterString_all`
70. `hiddenSubscriptionEndDate_viSoln`
71. `hiddenUISequenceForModelSelection_viSoln`
72. `hiddenUISequenceMasterString_viSoln`
73. `hideUDCCFlag_all`
74. `htmlToForcedSet_RecommendedConfigurationAttributes_viSoln`
75. `includeASpareBatteryWithEachBodyCamera_viSoln`
76. `isMountingTypeJacketClipMount_viSoln`
77. `isMountingTypeJacketMagneticMount_viSoln`
78. `isMountingTypeLockingMolleMount_viSoln`
79. `isMountingTypeShirtClipMount_viSoln`
80. `isMountingTypeTEKLOKBeltMount_viSoln`
81. `isOptAccessoriesSVX12SlotBatteryOnlyChargerQuantity_viSoln`
82. `isOptAccessoriesSVX12SlotBatteryOnlyCharger_viSoln`
83. `iscustomernotfederal_viSoln`
84. `ismountingtypeShirtMagneticMount_viSoln`
85. `magneticCharger_viSoln`
86. `modelSelectionBaseModel_viSoln`
87. `modelSelectionRegion_viSoln`
88. `modelSelectionSelectModel_viSoln`
89. `mountType_viSoln`
90. `mountingArrayControl_viSoln`
91. `mountingTypeArray_viSoln`
92. `mountingTypeArrayqty_viSoln`
93. `mountingTypeJacketClipMountQuantity_viSoln`
94. `mountingTypeJacketMagneticMountQuantity_viSoln`
95. `mountingTypeLockingMolleMountQuantity_viSoln`
96. `mountingTypeShirtClipMountQuantity_viSoln`
97. `mountingTypeShirtMagneticMountQuantity_viSoln`
98. `mountingTypeTEKLOKBeltMountQuantity_viSoln`
99. `nSBomFlag`
100. `nonFrequencyParametricData_viSoln`
101. `nonMandatoryPartsListString_all`
102. `packageInvokedFlag`
103. `paymentPlanDurationDummyAttribute_viSoln`
104. `paymentPlanDuration_viSoln`
105. `previousCounterForNonMandatoryParts_viSoln`
106. `productDescriptionHelpText_viSoln`
107. `productInformationText_viSoln`
108. `productSelectionProduct_all`
109. `quantityOfBodyWornCamerasDummyAttribute_viSoln`
110. `quantityOfUploadSmartDocksDummyAttribute_viSoln`
111. `quantityOfUploadSmartDocks_viSoln`
112. `rSMBasePrice_viSoln`
113. `refreshAttrName`
114. `refreshDuration_viSoln`
115. `refreshHelpText_viSoln`
116. `refresh_viSoln`
117. `refreshdummy_viSoln`
118. `renewalDuration_viSoln`
119. `sIFormulaVersion_viSoln`
120. `sMP3_1_CONFIG_FLAG`
121. `sVXTAAKitHelpText_viSoln`
122. `salesContactEmailAddress_viSoln`
123. `salesContactNameForThisOrder_viSoln`
124. `salesQuoteCotermFlag_viSoln`
125. `saveChanges_RecommendedConfiguration_viSoln`
126. `serviceType_viSoln`
127. `smartDockConfigServiceNoVideoStorage_viSoln`
128. `smartDockExtendedWarranty_viSoln`
129. `solutionCategoryPreviousValues_viSoln`
130. `subsDuration_viSoln`
131. `systemEnggAttributeValueString_viSoln`
132. `trainingCostFactorMasterString_viSoln`
133. `uDCCOverrideWarningHelpText`
134. `ultimateDestinationCountry`
135. `v300BodyWornCamera_viSoln`
136. `validationOrg`
137. `wouldYouLikeToIncludeABatterySubscription_viSoln`

---

## 4. THE concrete mechanism — section grouping within the flow (not just flow membership)

Flow-rule membership (§1, 350 attrs) is NECESSARY but not SUFFICIENT to explain the screenshot — it scopes everything relevant to this device's whole configuration process, including backend plumbing. The actual on-screen grouping is a SECOND, finer signal: `bm_layout_model.parent_id`.

**Checked directly**: every screenshot field (`ultimateDestinationCountry`, `productSelectionProduct_all`, `softwareBundlesBundleType_astro`, `packageTypeBundles_astro`, `isProvisioningRequiredInCloudEnv_astro`, `solutionTypeDevices_astro`) shares the EXACT SAME `parent_id=22194397375` -- a `bm_layout_model` node with `model_obj_type=3` (a SECTION/GROUP container -- distinct from `model_obj_type=5`, the FIELD nodes themselves). Their `order_number`s (1, 2, 6, 7, 10, 15) match the screenshot's exact top-to-bottom sequence.

**This one section has 35 total attributes** (order 1-35) -- the screenshot shows roughly the first 15 (scrolled to that viewport position); the remaining 20 (solution duration, app services, SIM card selection, wireless carrier, battery type, etc.) render further down the SAME page, not on a different page and not hidden.

**Two sampled plumbing/helper attributes sit under DIFFERENT parent_ids** -- `packageChoiceString` (parent_id=22194397479) and `hiddenRowSeparator_allFamily`/`hidddenRecordSeparator_allFamilly` (parent_id=22194397483) -- different sections entirely, never rendered as part of this visible group. This is the real reason most of the 350 flow-scoped attrs never appear in this screenshot: they belong to OTHER sections (other steps/tabs, or backend-only groups), not because flow-membership itself implies visibility.

**One open thread, not glossed over**: `hWVersion_astro` (visibly in the screenshot, between Country and Product) is NOT present under this specific `layout_id=22194396998` copy at all -- its `layout_attr_assoc` rows point at the OTHER two near-duplicate layout_id variants (`19435393493`, `22194397000`) instead. The 3 layout_id copies likely represent parallel flow variants (e.g. New Order vs Modify Order vs a System-Config path) that the real UI picks between based on a condition not yet identified from the DB alone -- worth a follow-up check before this becomes part of an implementation.

**Revised model for tier 1 of the §2 fallback plan**: scope to the flow rule's attrs (§1), THEN group/order by `parent_id`/`order_number` within it (this section) -- flow membership alone under-scopes (includes plumbing); parent_id grouping is what actually matches the real rendered page.
---

## 5. Generic identification rule — verified on BOTH catalogs

Confirmed the raw `parent_id` is NOT a usable identifier across catalogs: APX Next's country-anchor section is parent_id=22194397375 under layout_id=22194396998; SVX's is parent_id=22194441086 under a completely different layout_id=22194441070 -- auto-generated, catalog-specific keys, never comparable across exports.

**Worse than expected**: even the two "obvious" anchor attributes don't co-locate reliably. In APX Next, `ultimateDestinationCountry` and `productSelectionProduct_all` share ONE section (order 1, 2). In SVX they do NOT -- `productSelectionProduct_all` sits in a totally different group, at order 30/38, far down its own form. A rule based on "the group containing country + product" would fail on SVX.

**What IS stable, verified on both**: `ultimateDestinationCountry` sits at `order_number=1` within its own containing layout_model group, in EVERY layout_id variant, in BOTH catalogs. This attribute is already privileged by `CpqEngine` today as the D1 country anchor -- no new hardcoding needed, just reuse of an existing semantic anchor.

**Identification rule (verified, not just proposed)**: the primary visible section = the `bm_layout_model` group whose `order_number=1` (or lowest) member is the resolved `ultimateDestinationCountry`-type attribute (same country-anchor detection `CpqEngine` already uses), within the catalog's flow-rule scope (§1). Applied to SVX, this correctly reproduces a coherent 15-attribute starting section (country, warning text, archetype/model selection, camera options, refresh settings, mounting options) -- structurally analogous to APX Next's 35-attribute section despite having a completely different attribute set, confirming the rule generalizes by STRUCTURE, not by content.

**Net update to §2's tier 1**: scope by flow-rule membership, THEN locate "the section" via the country-anchor's own group (not a hardcoded ID, not a fixed anchor-attribute cluster) -- this is the concrete, catalog-agnostic version of the parent_id grouping found in §4.
---

## 6. Correction + the fourth layer: hiding rules gate individual fields within a section

§4/§5 picked one of APX Next's 3 near-duplicate layout_id copies (22194396998) to identify the visible section. That copy omits `hWVersion_astro` entirely -- checked the other two copies and found the one that actually matches the screenshot: `layout_id=22194397000`, `parent_id=22194397030` -- 32 attrs, order 1=Country, 2=Hardware Version, 3=Product, 4=help text, 5=Frequency Bands, 6=Frequency Band Plus, 7=Software Bundles Type ("Configuration Type" in the UI), 8=Package Type Bundles ("Software Bundles" checkboxes) -- an exact match to the screenshot's field order.

**Why orders 4, 5, 6 don't render as visible fields while 7 does** -- checked layout properties first (identical across all four, ruled out), then found the real cause: **5 active hiding rules (`rule_type=11`)**, all following the SAME idiom -- a script that `SPLIT()`s a per-selected-base-model "enabled attributes" string (`hiddenUISequenceForModelSelection_astro` / `hiddenMasterStringForAstroPortable_astro`, delimited by `hidddenRecordSeparator_allFamilly`) and checks `findinarray()` for whether this specific attribute's name appears in it:

| Rule | Target | Idiom |
|---|---|---|
| "Hide Model selection frequency band attribute" | `modelSelectionFrequencyBands_astro` | hidden unless listed in the selected model's enabled-attribute string |
| "Hide Model Selection Frequency Band Plus if no values available" | `modelSelectionFrequencyBandPlus_astro` | same idiom |
| "Hide Product Selection helptext if no values available" + a second, more specific rule | `productSelectionHelptext_astro` | same idiom, plus hidden unless frequency band is 700/800·VHF·UHF for Enhanced/XE/XN-5G products |
| "Hide Bundle type If no Values Available" | `softwareBundlesBundleType_astro` | same idiom |
| "Hide all attributes if Product is Blank" | all four | declarative — hides all of them if `productSelectionProduct_all` is empty |

**The pattern**: for the currently-selected base model (APX NEXT 4G LTE+5G -- a single-band SKU), that model's own enabled-attribute string does NOT list the frequency-band fields or their help text (no band ambiguity to resolve on a single-band model) -- but DOES list Software Bundles Type. Same mechanism, opposite outcome, driven entirely by which model was picked.

**Connection to `docs/CPQ_RULE_TOOL_FLOW_PLAN.md` §16 (BML coverage plan)**: these 5 scripts use `SPLIT()`/`findinarray()` against a LOCAL script variable, not a direct attribute comparison -- they don't fit the Tier-1 if/else grammar `bml.py` already parses, so they fall to "unknown -> stay visible" even with this session's fixes. This is a genuinely new, real idiom ("per-model enabled-attribute list lookup") for the Tier-1.5 roadmap -- confirmed live-relevant (it's exactly what gates the screenshot's own fields), not a hypothetical case.

**Net model, four layers stacking together**: (1) flow-rule membership (§1) scopes what's relevant to this device at all; (2) section/`parent_id` grouping (§4/§5) scopes what's on THIS page, in what order; (3) the country-anchor identification rule (§5) finds that section generically; (4) ordinary hiding rules (already partially handled by the rule_tool plan, this specific idiom not yet) decide which of the section's fields are ACTUALLY shown for the current selections. No single layer explains the screenshot alone.
---

## 7. Third catalog confirmation — SL3500e_config.xml

Checked a third, independent file (`SL3500e_config.xml`, 17MB, MOTOTRBO/SL3500e catalog) against every claim in this plan.

| | APX Next | SVX Video RSM | SL3500e |
|---|---|---|---|
| `rule_type=6` count | 3 | 2 | **2** |
| Flow rule names | "Configuration Flow For Astro Devices (Portable)" + "_sysConfig" | "Configuration Flow For vX650 (Video Solutions_BOM)" + "_SysConfig" | **"Configuration Flow For Region NA"** + **"Configuration flow for MotoTrbo model series"** |
| `layout_attr_assoc` rows dominated by flow rule_ids | top 3 | top 2 = 100% of 266 | **top 2 = 100% of 331** |
| Attrs with layout placement | 350/427 (82%) | 137/235 (58%) | **186/277 (67%)** |
| Country anchor at `order_number=1` in its own section | ✅ | ✅ | **✅ (both layout_id variants)** |

Naming varies again ("Region NA" / "MotoTrbo model series" instead of device-class names) — confirming the RULE NAME itself is never a safe signal, only `rule_type=6` + the layout_attr_assoc dominance pattern is. The country-anchor section here is small (2 attrs: country + its warning help text) — a plausible, real difference in how this catalog's designer split sections, not a break in the rule.

**Net**: every mechanism in this plan (§1 flow rule, §2 fallback design, §4 section grouping, §5 country-anchor identification) is now confirmed on THREE independent catalogs, not two. No changes needed to the plan itself — this round was verification, not new discovery.