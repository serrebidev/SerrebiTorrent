# Changelog

All notable changes to SerrebiTorrent are recorded here.

## v1.31.0 - 2026-10-08

- Enforce disk-space reserve during active downloads (#401).

## v1.30.0 - 2026-10-08

- Pause seeding at a configurable ratio target (#400).

## v1.29.0 - 2026-10-07

- Add safe stalled torrent recovery action (#399).
- Remember recent torrent save destinations (#398).
- Move completed torrent data automatically (#397).
- Add profile-scoped torrent categories (#395).
- Compose category and name torrent filters (#396).

## v1.28.0 - 2026-10-07

- Add persistent accessible activity history (#394).
- Protect disk-space reserve before torrent file adds (#393).

## v1.27.0 - 2026-10-07

- Add per-torrent download and upload limits (#392).

## v1.26.0 - 2026-10-06

- Move torrent data across supported clients (#391).

## v1.25.1 - 2026-10-06

- Maintenance update.

## v1.25.0 - 2026-10-06

- Add cross-client torrent queue controls (#390).
- Optionally notify when downloads complete (#388).
- Diagnose stalled torrents (#387).

## v1.24.0 - 2026-10-06

- Expose Web Start All and Stop All actions (#386).
- Expose Start All and Stop All desktop actions (#384).
- Optionally pause torrents when downloads complete (#383).
- Filter desktop torrents by name (#381).
- Add accessible Web torrent sorting (#382).

## v1.23.0 - 2026-10-06

- Add keyboard access to Web torrent filter (#379).
- Add Web Select none keyboard shortcut (#380).
- Add Select none keyboard shortcut (#377).
- Filter Web torrents by name (#376).
- A11y: announce completed downloads in Web UI (#378).
- A11y: announce completed downloads to screen readers (#375).

## v1.22.39 - 2026-10-05

- I18n: translate Clear All button text (#372).
- I18n: localize Deselect row labels (#373).
- I18n: localize Web toolbar action labels (#374).
- I18n: translate Select All button announcement (#371).
- Merge PR #369.
- Merge PR #350.
- Merge PR #356.
- Merge PR #362.
- Merge PR #365.
- Merge PR #367.
- I18n: translate Space selection feedback (#368).
- I18n: localize Web accessible action labels (#370).
- I18n: translate Web torrent row status (#366).
- I18n PR #351.
- I18n PR #357.
- I18n PR #360.
- I18n: translate remove-with-data confirmation (#363).
- I18n: translate torrent focus recovery (#359).
- I18n: translate remote settings exception feedback (#358).
- I18n: translate torrent-removed refresh feedback (#361).
- I18n: translate profile-switch announcement (#346).
- I18n: translate empty-list focus recovery (#348).
- I18n: translate clipboard success announcement (#347).
- I18n: translate select-all announcement (#349).
- I18n: translate settings save error feedback (#352).
- I18n: translate clear-all feedback (#353).
- I18n: translate settings exception feedback (#354).
- I18n: translate action-menu guidance (#341).
- I18n: translate selection-cleared announcement (#342).
- I18n: translate empty-selection action warning (#343).
- I18n: translate menu-open announcement (#344).
- I18n: translate menu-close announcement (#345).

## v1.22.38 - 2026-10-05

- Allow local paths in Web profile form (#331).
- Preserve tracker sidebar focus on removal (#332).
- Preserve profile sidebar focus on removal (#333).
- Keep Web select-all name in sync (#334).
- Refresh details after Web Ctrl+A (#335).
- I18n: translate empty Web details state (#338).
- I18n: translate remote settings loading state (#336).
- I18n: translate empty remote settings state (#337).
- Disable Web select-all controls when empty (#339).
- I18n: translate Web torrent detail labels (#340).

## v1.22.37 - 2026-10-04

- A11y: contextualize RSS rule editor actions (#321).
- A11y: name runtime RSS reset action (#322).
- A11y: contextualize indexer manager dialog actions (#323).
- A11y: name Web preferences trigger explicitly (#327).
- A11y: contextualize Web settings modal close (#324).
- A11y: contextualize Web torrent actions menu (#325).
- A11y: contextualize Web select-all action (#326).
- A11y: name Web logout action explicitly (#328).
- A11y: contextualize Web create-profile submit (#329).
- A11y: contextualize Web Add Torrent submit (#330).
- A11y: contextualize Web profile modal close (#319).
- A11y: contextualize runtime Add Torrent actions (#317).
- A11y: contextualize Web Add Torrent modal close (#320).
- A11y: contextualize torrent creator actions (#318).
- A11y: contextualize runtime preferences actions (#316).
- A11y: contextualize indexer manager actions (#315).
- A11y: name search add-selected action (#311).
- A11y: contextualize search-sites dialog actions (#313).
- A11y: contextualize indexer editor actions (#314).
- A11y: name search-site selection actions (#312).

## v1.22.36 - 2026-10-04

- A11y: name torrent search actions contextually (#310).
- A11y: name RSS rules close action (#309).
- A11y: contextualize remote settings actions (#307).
- A11y: contextualize preferences dialog actions (#306).
- A11y: name Add Torrent deselect-all action (#302).
- A11y: name Add Torrent select-all action (#301).
- A11y: contextualize Add Torrent dialog actions (#303).
- A11y: name RSS reset action contextually (#305).
- A11y: contextualize profile dialog actions (#304).

## v1.22.35 - 2026-10-04

- Update dependencies and test tooling.
- Update GitHub Actions to Node 24-compatible versions (cache v5).

## v1.22.34 - 2026-10-03

- A11y: add RSS toolbar keyboard mnemonics (#297).
- A11y: contextualize Web toolbar actions (#298).
- Clarify tracker removal action (#299).
- A11y: contextualize connection dialog actions (#300).

## v1.22.33 - 2026-09-30

- Refine Web torrent form input semantics (#295).

## v1.22.32 - 2026-09-30

- Reject invalid RSS regex rules (#290).
- Bound qBittorrent version response (#291).
- Report partial Web delete results (#292).
- Handle translation draft save failures (#289).
- Validate Authenticode JSON object shape (#286).
- Bound torrents database writes (#287).
- Reject malformed translation drafts (#285).
- Require string torrent hashes in Web snapshots (#288).
- Validate updater JSON object shape (#284).
- Reject oversized RSS feeds early (#282).
- Reject invalid default profile ids (#283).
- Bound translation draft writes (#281).
- A11y: add Connection Manager keyboard mnemonics (#294).
- A11y: name Translation Center actions contextually (#296).
- A11y: expose Web torrent progress percentage (#293).

## v1.22.31 - 2026-09-30

- Reject malformed remote preference reads (#277).
- Resolve relative RSS and Atom links (#278).
- Refresh after partial Web bulk action (#279).
- Clear current profile after connection failure (#280).

## v1.22.30 - 2026-09-30

- Restore desktop preference rollback (#274).
- Keep torrent output outside source tree (#275).
- Normalize persisted RSS articles (#276).
- Finish stale client worker guards (#273).
- Normalize structured search preferences (#271).
- Batch large Web torrent actions (#272).
- Ignore stale client worker results (#270).
- Support Atom RSS feeds (#269).
- Reject oversized torrent downloads early (#267).
- Prevent torrent creator from overwriting source (#268).
- Persist RSS refresh state (#266).
- Close rejected search response streams (#265).
- Add CHANGELOG.md maintained from release notes, like BlindRSS.

## v1.22.29 - 2026-09-29

- Maintenance update.

## v1.22.28 - 2026-09-29

- Bound built-in search responses (#264).
- Normalize nested RSS state fields (#262).
- Validate loaded profile schema (#261).
- Bound Web torrent action batch size (#263).
- Bound RSS state writes to read limit (#260).
- Filter malformed RSS state entries (#258).
- Bound Web torrent add batch size (#259).
- Drop malformed profiles during normalization (#256).

## v1.22.27 - 2026-09-29

- Preserve structured remote preferences (#255).
- Bound config writes to read limit (#252).
- Normalize malformed scalar preferences (#254).
- Validate remote preference types (#253).

## v1.22.26 - 2026-09-29

- Roll back Web prefs when live apply fails (#248).
- Reject booleans in numeric Web preferences (#250).
- Roll back desktop prefs when live apply fails (#249).
- Bound Web string preferences (#251).

## v1.22.25 - 2026-09-29

- Maintenance update.

## v1.22.24 - 2026-09-29

- Validate Web app preference types (#244).
- Translate and clarify Web clipboard settings (#245).
- Repair invalid boolean preference types (#246).
- Translate contextual accessible names to pt-BR (#247).
- Translate clipboard preferences to pt-BR (#241).
- Translate magnet intake feedback to pt-BR (#242).
- Expose clipboard preferences in Web UI (#240).

## v1.22.23 - 2026-09-29

- Distinguish localized Add Torrent actions (#238).
- Name dynamic remote preference controls (#237).
- Distinguish localized RSS actions (#239).

## v1.22.22 - 2026-09-28

- Fix native tracker-merge test on libtorrent 2.1: use _torrent_status_flag instead of removed torrent_status.paused.
- Add optional clipboard torrent intake, duplicate tracker merging across backends, and Transmission fixes (#210).

## v1.22.21 - 2026-09-28

- Attach RSS delete name to RSS rule button (#236).
- Distinguish torrent creator tracker actions (#233).
- Distinguish RSS rule actions (#234).
- Distinguish modern connection actions (#232).
- Distinguish RSS feed actions (#235).

## v1.22.20 - 2026-09-28

- Distinguish connection Browse button (#229).
- Distinguish torrent creator picker buttons (#230).
- Distinguish connection manager actions (#231).
- Name add torrent dialog controls (#228).
- Complete active preference control names (#226).
- Name active profile dialog controls (#227).
- Improve remote profile form semantics (#223).
- Reset RSS through live manager (#221).
- Reflect torrent checkbox action (#224).
- Name active preference controls (#225).
- Reflect Web select-all action (#222).
- Restore persisted Web UI theme (#220).
- Distinguish preference Browse buttons (#219).
- Name Web UI selection checkboxes (#216).
- Surface Web app setting limits (#217).
- Persist Web UI refresh rate (#218).
- Make removal state cleanup transactional (#206).
- Keep FlexGet profile imports in live config (#214).
- Apply Web UI transfer limits immediately (#215).
- Bound persisted web secret reads (#212).
- Apply Web UI RSS interval immediately (#213).
- Bound blindDL config reads (#211).

## v1.22.19 - 2026-09-28

- Hide unsupported remote file selection (#209).
- Retry watch files after profile changes (#207).
- Invalidate search callbacks on close (#208).

## v1.22.18 - 2026-09-28

- Bound custom indexer responses (#204).
- Make translation drafts atomic and bounded (#205).

## v1.22.17 - 2026-09-28

- Bound torrents DB reads (#202).
- Bound tracker list downloads (#203).
- Bound qBittorrent version state reads (#198).
- Block credentialed indexer redirects (#199).
- Bound translation catalog reads (#200).
- Bound GitHub release metadata (#201).

## v1.22.16 - 2026-09-28

- Bound persisted RSS state reads (#194).
- Key tracker cache by source URL (#196).
- Validate remote profile ports (#197).
- Report partial batch removals (#195).

## v1.22.15 - 2026-09-28

- Maintenance update.

## v1.22.14 - 2026-09-28

- Name RSS editor controls for screen readers (#190).
- Label Web settings tab panels (#191).
- Focus connection dialog entry controls (#192).
- Clarify port mapping diagnostics (#193).

## v1.22.13 - 2026-09-28

- Name RSS rules list for screen readers (#189).
- Name RSS rules list for screen readers (#184).
- Bound config JSON reads (#188).
- Name create torrent controls for screen readers (#187).
- Bound persisted session state reads (#186).

## v1.22.12 - 2026-09-28

- Name torrent search status for screen readers (#181).
- Expose Web Select All toggle state (#183).
- Name desktop status bar for screen readers (#185).
- Name preference controls for screen readers (#179).
- Connect selected profile with Enter (#180).
- Label Web toolbar icon buttons (#182).

## v1.22.11 - 2026-09-28

- Maintenance update.

## v1.22.10 - 2026-09-28

- Report create-torrent clipboard failures accurately (#176).
- Report torrent search clipboard failures (#177).
- Validate updater redirects before following (#178).

## v1.22.9 - 2026-09-28

- Bound desktop FlexGet imports (#173).
- Reuse created torrent bytes when adding (#172).

## v1.22.8 - 2026-09-28

- Harden search torrent downloads (#169).

## v1.22.7 - 2026-09-28

- Bound CLI torrent file reads (#167).
- Report failed resume saves accurately (#168).
- Normalize Web torrent action hashes (#170).

## v1.22.6 - 2026-09-28

- Bound manual torrent file reads (#166).
- Report partial Web torrent adds (#165).
- Lock RSS Web mutation prechecks (#164).
- Preserve torrent metadata on resume updates (#163).

## v1.22.5 - 2026-09-27

- Label add profile icon button (#162).
- Let Enter confirm add torrent dialog (#161).
- Require rTorrent SCGI port (#160).
- Rollback torrent removal DB failures (#159).

## v1.22.4 - 2026-09-27

- Handle missing Clipboard API (#155).
- Report profile validation errors (#158).
- Use unique writable-directory probe (#157).
- Validate remote profile endpoints (#156).

## v1.22.3 - 2026-09-27

- Write created torrents atomically (#154).
- Prevent watch-folder reimports after mark failure (#153).
- Reject credentials in profile URLs (#152).
- Rollback add persistence failures (#151).

## v1.22.2 - 2026-09-26

- Drop duplicated FlexGet upload test from #146.
- Rollback file priority save failures (#149).
- Restrict data directory permissions (#148).
- Harden RSS feed URLs (#147).
- Bound FlexGet config uploads (#146).
- Bound FlexGet config uploads to 2 MB (fixes #145).
- Lock RSS Web snapshots (#143).
- Propagate rTorrent stats failures (#144).
- Restrict remote preference writes (#142).

## v1.22.1 - 2026-09-26

- Restore Web UI a11y suite and darken secondary button below AA threshold.
- Wire Web profile creation form (#137).
- Bound watch-folder torrent reads (#138).
- Validate FlexGet RSS feed URLs (#139).
- Validate and format listen interface (#140).

## v1.22.0 - 2026-09-26

- Add listen interface setting so UPnP maps the right NIC (#103).

## v1.21.14 - 2026-09-26

- Match disabled indexers case-insensitively (#136).
- Bound rTorrent SCGI responses (#135).
- Minimize Web profile metadata (#134).
- Make Web action feedback accessible (#133).

## v1.21.13 - 2026-09-26

- Announce remote settings load failures (#131).
- Restrict session log permissions (#129).
- Bound Web torrent uploads (#130).
- Restrict Web application preference writes.

## v1.21.12 - 2026-09-26

- Report Web clipboard failures (#126).
- Redact remote preference secrets (#125).
- Announce Web profile load failures.
- Report Web settings load failures.

## v1.21.11 - 2026-09-26

- Report Web profile switch failures (#124).
- Keep local settings out of remote preferences (#123).
- Deduplicate indexer names case-insensitively (#122).
- Require portable write-probe cleanup (#121).

## v1.21.10 - 2026-09-26

- Restrict local torrent state permissions (#119).
- Make late search results actionable (#120).
- Bound private torrent downloads (#118).
- Redact secrets from Web app preferences (#117).

## v1.21.9 - 2026-09-26

- Restrict torrent database permissions (#113).
- Restrict RSS state file permissions (#112).
- Harden qBittorrent version cache (#114).
- Redact profile passwords from Web API (#116).
- Report local preference save failures (#115).

## v1.21.8 - 2026-09-26

- Restrict Web session key permissions (#109).
- Restrict config file permissions (#108).
- Report profile persistence failures in dialog (#111).
- Keep blindDL auto-import persistence optional (#110).

## v1.21.7 - 2026-09-25

- Keep existing macOS data under ~/.local/share.
- Tolerate malformed blindDL config roots (#107).
- Use Application Support for macOS user data (#106).
- Write Web session key atomically (#105).
- Preserve unreadable RSS configuration (#104).
- Log UPnP and NAT-PMP port mapping results (#103).

## v1.21.6 - 2026-09-25

- Keep torrent metadata in resume data (#83).
- Roll back failed RSS download marks (#100).
- Preserve unreadable torrents database (#101).

## v1.21.5 - 2026-09-25

- Revalidate updater redirect targets (#99).
- Roll back failed RSS rule toggles (#98).

## v1.21.4 - 2026-09-25

- Report rejected RSS feed URLs instead of crashing the handler.
- Validate RSS feed URLs before saving (#97).
- Preserve unsubmitted Web app preferences (#96).

## v1.21.3 - 2026-09-25

- Stop the watch folder failing silently (#95).

## v1.21.2 - 2026-09-25

- Preserve unreadable config during fallback (#94).
- Roll back failed RSS reset (#93).

## v1.21.1 - 2026-09-24

- Report missing local torrent action targets (#92).
- Reject malformed torrent snapshot entries (#91).
- Block private-network RSS fetches (#89).
- Require CSRF protection for Web logout (#90).

## v1.21.0 - 2026-09-24

- Log local session diagnostics.
- Propagate remote preference read failures (#88).
- Reject invalid torrent snapshot results (#87).
- Reject invalid torrent detail results (#86).
- Reject null remote settings reads (#85).
- Propagate rTorrent detail read failures (#84).

## v1.20.5 - 2026-09-24

- Continue batch delete after failures (#80).
- Propagate torrent snapshot failures (#81).

## v1.20.4 - 2026-09-24

- Make preference saves transactional (#78).
- Make profile mutations transactional (#77).

## v1.20.3 - 2026-09-24

- Continue batch resume and pause after failures (#76).
- Report torrent sync read failures (#75).
- Handle profile switch lookup failures (#74).
- Report open folder as asynchronous (#73).

## v1.20.2 - 2026-09-24

- Report disconnected torrent add (#72).
- Report torrent stats read failures (#71).

## v1.20.1 - 2026-09-24

- Preserve profile sidebar on read failures (#70).
- Validate remote settings writes (#69).
- Report missing RSS read context (#68).
- Make FlexGet imports report real outcomes (#67).
- Report app settings read failures (#66).
- Report remote settings read failures (#65).
- Preserve Web torrent state on refresh failures (#64).
- Make Web RSS rule persistence reliable (#63).
- Report profile switch as asynchronous (#62).
- Make Web RSS feed persistence reliable (#61).
- Harden Web torrent files endpoint (#60).
- Report Web settings persistence failures (#59).

## v1.20.0 - 2026-09-23

- Populate the Web torrent Trackers details tab (#57).
- Vendor Bootstrap for offline Web UI (#58).

## v1.19.0 - 2026-09-23

- Populate the Web torrent Peers details tab (#55).
- Add Web torrent trackers endpoint (#56).
- Dedupe release notes and drop merge commit subjects.

## v1.18.0 - 2026-09-23

- Add Web torrent peers endpoint.
- Populate Web torrent files tab.
- Localize Files tab and ignore stale responses.
- I18n: sync Files tab source template.
- I18n: sync Web catalog source casing.
- I18n: sync pt-BR Files tab Web catalog.
- I18n: remove duplicate Torrent actions source.
- I18n: update pt-BR Files tab catalog.
- I18n: register Web Files tab strings.
- I18n: unify Torrent Actions source casing.
- A11y: label Web torrent detail tabpanels.

## v1.17.0 - 2026-09-23

- Add bulk torrent import and watch folder.
- Report Web profile persistence failures.
- Validate Web profile creation.
- Merge pull request #52 from CIATA-BR/ciata/validate-web-profile-create.

## v1.16.8 - 2026-09-23

- Find updates when the GitHub API is rate limited.

## v1.16.7 - 2026-09-23

- Validate Web profile switches.
- Harden Web remove action failures.
- Serialize Web torrent refreshes.
- Report Web torrent action failures.
- I18n: translate Web torrent action errors.
- Merge pull request #49 from CIATA-BR/ciata/validate-web-profile-switch.
- Merge pull request #48 from CIATA-BR/ciata/harden-web-remove-action.
- Merge pull request #47 from CIATA-BR/ciata/serialize-web-refresh.
- Merge pull request #46 from CIATA-BR/ciata/report-web-action-failures.

## v1.16.6 - 2026-09-23

- Keep a Tab stop in every sidebar listbox.
- Rebuild sidebar lists only when their data changes.
- Merge pull request #45 from CIATA-BR/ciata/announce-web-action-success.
- Merge main into ciata/announce-web-action-success.
- Merge pull request #44 from CIATA-BR/ciata/sidebar-listbox-scope.
- A11y: pass action labels to Web success feedback.
- A11y: announce successful Web torrent actions.
- A11y: scope sidebar roving focus to each listbox.
- Merge pull request #43 from CIATA-BR/ciata/remove-duplicate-sidebar-clicks.
- Merge pull request #42 from CIATA-BR/ciata/preserve-sidebar-focus-refresh.
- A11y: remove duplicate inline sidebar filter handlers.
- A11y: preserve sidebar focus across dynamic refreshes.

## v1.16.5 - 2026-09-23

- Let arrow keys enter the rows from the focused grid.
- Merge pull request #40 from CIATA-BR/ciata/scope-web-grid-keyboard.
- Merge main into ciata/scope-web-grid-keyboard.
- Merge pull request #41 from CIATA-BR/ciata/sidebar-explicit-activation.
- A11y: require explicit activation in Web sidebar.
- Merge main into ciata/scope-web-grid-shortcuts.
- A11y: scope Web grid keyboard shortcuts to focused rows.

## v1.16.4 - 2026-09-23

- Speak Web announcements raised together and repair a11y tests.
- Retranslate every catalog and translate dynamic Web messages.
- Only clear the install once the update is being applied.
- Check the torrent download peer when the socket connects.
- Restore the repository files deleted by the #35 merge.
- Remember direct action-menu trigger.
- Restore focus after Web overlays close.
- Toggle Web torrent selection with Space.
- Associate Web modal labels with controls.
- Keep focus on the empty torrent grid.
- Preserve Web list focus when torrents disappear.
- Rebuild transactional updater rollback cleanly.
- Make updater rollback transactional.
- Merge pull request #39 from CIATA-BR/ciata/web-session-expiry-feedback.
- A11y: explain expired sessions on the login page.
- A11y: preserve session-expiry context before Web login redirect.
- Merge pull request #38 from CIATA-BR/ciata/announce-web-list-changes-v2.
- A11y: announce material Web torrent list changes.
- Merge pull request #35 from CIATA-BR/ciata/pause-web-refresh-in-modals.
- A11y: pause Web background refresh while dialogs are open.
- Merge pull request #34 from CIATA-BR/ciata/focus-web-modal-entry.
- A11y: focus useful controls when Web modals open.
- A11y: declare initial focus for Web modals.
- Merge pull request #33 from CIATA-BR/ciata/restore-web-overlay-focus.
- Merge pull request #32 from CIATA-BR/ciata/web-space-toggle-selection.
- Merge pull request #29 from CIATA-BR/ciata/preserve-web-focus-on-refresh.
- Merge pull request #30 from CIATA-BR/ciata/label-web-modal-controls.
- Merge pull request #31 from CIATA-BR/ciata/update-helper-visible-launch-test.
- Merge pull request #28 from CIATA-BR/ciata/transactional-updater-rollback.
- Merge pull request #27 from CIATA-BR/ciata/harden-torrent-url-rebinding.
- Keep Web URL validation side-effect free.
- Remove duplicate Web URL preflight request.
- Verify torrent download peer address.

## v1.16.3 - 2026-09-23

- Validate Translation Center language codes before export (#19).
- Harden cloud release permissions and native wheel trust (#26).

## v1.16.2 - 2026-09-23

- Maintenance update.

## v1.16.1 - 2026-09-22

- Complete every translation catalog and drop corrupted fuzzy entries.

## v1.16.0 - 2026-09-22

- Start the Translation Center from the shipped catalog and import PO files.

## v1.15.3 - 2026-09-22

- Report malformed bundle JSON instead of crashing.

## libtorrent-wheels - 2026-09-23

- Maintenance update.

## v1.15.2 - 2026-09-21

- Fail the bundle audit when a shipped catalog loses a required message.

## v1.15.1 - 2026-09-21

- Translate the Web login lockout message in every catalog.

## v1.15.0 - 2026-09-21

- Report and gate translation coverage.
- Report Web login lockout separately from invalid credentials.
- Cross-check the GitHub release asset digest.
- Bound the Web login throttle and harden response headers.

## v1.14.6 - 2026-09-21

- Maintenance update.

## v1.14.5 - 2026-09-21

- Keep stale language preferences aligned with fallback.
- Reject locale filename and Language header drift.
- Localize login from generated community catalogs.
- Expose translation JSON to unauthenticated login.
- Keep web language selector aligned with fallback.
- Show effective fallback for stale desktop language.
- Enforce canonical locale catalog filenames.
- Merge pull request #18 from CIATA-BR/ciata/localize-web-login-from-catalogs.

## v1.14.4 - 2026-09-21

- Activate external desktop catalogs at startup.
- Prune stale generated Web catalogs.
- Merge pull request #14 from CIATA-BR/ciata/audit-packaged-translations.
- Merge pull request #15 from CIATA-BR/ciata/activate-external-desktop-catalogs.
- Merge pull request #13 from CIATA-BR/ciata/prune-stale-web-catalogs.
- Verify translation assets in standalone bundle.

## v1.14.3 - 2026-09-21

- Preflight translation generation before writes.
- Reject normalized duplicate language codes.
- Validate catalog language codes.
- Merge pull request #12 from CIATA-BR/ciata/atomic-translation-generation.
- Merge pull request #11 from CIATA-BR/ciata/catalog-language-code-hardening.

## v1.14.2 - 2026-09-21

- Tighten the translation gate against the corruption the catalogs carry.
- Emit one release-notes bullet per commit.
- I18n: repair double-encoded catalogs and quarantine the remaining corruption.

## v1.14.1 - 2026-09-21

- Fail on malformed or duplicate translation catalogs.
- Harden translation integrity validation.
- Merge branch 'release/translation-integrity'.
- I18n: quarantine catalog entries that leak portal placeholders.
- I18n: keep the pt-BR accelerator mnemonic the source string declares.
- I18n: stop the community catalogs failing the hardened translation gate.
- Merge pull request #10 from CIATA-BR/ciata/pt-br-post-merge-wording.
- I18n: clean up pt-BR post-merge wording.
- Merge pull request #9 from CIATA-BR/ciata/i18n-test-isolation.
- Merge pull request #8 from CIATA-BR/ciata/strict-catalog-discovery.
- Merge pull request #7 from CIATA-BR/ciata/translation-validation-hardening.

## v1.14.0 - 2026-09-21

- Add community language catalogs.
- Merge pull request #6 from CIATA-BR/translations/pt-br-20260921-080804.
- I18n: update web language index.
- I18n: compile pt-BR web catalog.
- I18n: update pt-BR translation.

## v1.13.0 - 2026-09-21

- Add cross-platform translation pipeline and CIATA portal workflow (#5).
- Make the translation gate deterministic and the PO catalog live.
- Three defects prevented the translation pipeline from working:.
- Render_pot/render_po sorted by str.casefold alone. Four entries tie.
- Under casefolding ("Profiles"/"PROFILES", "Torrents"/"torrents",.
- "Torrent actions"/"Torrent Actions", "Check for updates"/"Check for.
- Updates"), so the output order followed set iteration order and hence.
- Six processes produced five different POT hashes and.
- `translation_tool.py check` failed roughly seven runs in eight on a.
- Correctly synced tree. Sort by (casefold, value) instead.
- _decode_po_string used strict json.loads, which rejects the raw tab.
- Characters in the reviewed catalog's wx accelerator labels. load_po.
- Raised, discover_catalogs swallowed it and returned {}, so the external.
- Pt-BR catalog never loaded on any platform and catalog_for("pt-BR") was.
- None. The same bug made `sync` rewrite web_static/locales/index.json to.
- {"languages": []}.
- Corrected six pt-BR entries that were wrong rather than merely.
- Start/Pause/Resume held "Starting/Pausing/Resuming.
- Torrents...", Uncheck held the past participle "Desmarcado", and.
- Checking/Seeding used nouns where the catalog elsewhere uses gerunds.
- Also declares X-Language-Name so regenerating the Web index keeps the.
- Native language label, regenerates the POT and Web catalogs, and points.
- The affected tests at the reviewed catalog instead of the legacy strings.
- Co-authored-by: CommandCodeBot <noreply@commandcode.ai>.
- Adds the external PO catalog runtime, the in-app Translation Center, the.
- Canonical locales/serrebitorrent.pot, the reviewed pt-BR catalog and the.
- Generated Web UI catalogs, wired through the localized entry point.
- The project memory index is maintained outside the repo now, so the.
- Generated block is no longer carried in agents.md.

## v1.12.0 - 2026-09-15

- Add localization foundation with pt-BR catalog (#4).
- Review follow-ups for localization and libtorrent 2.1 warnings.
- Pt-BR search dialog: "Ordenar p&or" and "Si&tes de pesquisa" so no two.
- Controls share an access key; test guards against future collisions.
- Create Torrent dialog honors the saved language preference.
- Restore explanatory comments dropped by the localization change.
- Dependency review uses actions/checkout@v7 and dependency-review-action@v5.
- Torrent_info.files() is deprecated in libtorrent 2.1; use layout() via.
- Torrent_parsing.torrent_file_storage, falling back on older bindings.
- README "Latest" now names v1.12.0 in both languages.
- Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>.
- Claude-Session: https://claude.ai/code/session_01J83QVukehLcJPL3gJVX7aE.
- * feat: add lightweight localization foundation.
- * test: cover localization fallback and pt-BR.
- * feat: persist interface language preference.
- * test: cover language preference migration.
- * feat(i18n): expand pt-BR search and indexer translations.
- * feat(i18n): localize torrent search dialogs.
- * test(i18n): cover pt-BR search UI catalog.
- * test(i18n): validate format placeholders in catalogs.
- * feat(i18n): add pt-BR torrent creator strings.
- * feat(i18n): localize create torrent dialog.
- * test(i18n): cover torrent creator translations.
- * test(i18n): allow language-neutral mnemonic labels.
- * docs: add Brazilian Portuguese README.
- * docs: add Brazilian Portuguese build guide.
- * docs: link Brazilian Portuguese README.
- * docs: link Brazilian Portuguese build guide.
- Shorten the Telegram intro line.

## v1.11.5 - 2026-08-16

- Make pause stick and honor start-paused preference (issue #1).
- Also fixes "Automatically start torrents = off" being ignored: libtorrent.
- A manual stop only called pause(), leaving the torrent auto-managed, so.
- Libtorrent's queue manager could restart it and the GUI's Stopped test.
- (paused and not auto_managed) never matched -- the row kept showing as.
- Active/seeding. LocalClient.stop_torrent now clears auto-management.
- Before pausing (via _handle_set_auto_managed, which works on 2.0 and.
- 2.1 flags).
- Auto-starts every added torrent, so adds now build add_torrent_params with.
- Auto_managed cleared when the preference is off (the dict 'flags' key is.
- Ignored by 2.1, so add_torrent_file switches to the object form).
- Adds unit tests for the stop/start-paused helpers and real-libtorrent.
- Integration tests for pause/resume list state and start-paused adds.
- ≡ƒñû Generated with Codebuff.
- Co-Authored-By: Codebuff <noreply@codebuff.com>.

## v1.11.4 - 2026-08-16

- Show Files/Peers/Trackers tabs on libtorrent 2.1 (issue #1).
- Libtorrent 2.1 renamed handle APIs that 2.0 had: has_metadata() is gone.
- (use status().has_metadata), get_torrent_info() became torrent_file(),.
- And file_priorities() became get_file_priorities(). LocalClient.get_files.
- Raised on the first call, and since the details panel swallows fetch.
- Exceptions the Files tab rendered empty while the app kept working. Route.
- All three through version-agnostic helpers (legacy attribute first, 2.1.
- Form second) and use the same metadata check in the session autosave and.
- Shutdown save paths, which were silently treating every 2.1 handle as.
- Having metadata.
- Adds real-libtorrent integration coverage for the Files/Peers/Trackers.
- Tabs, file priorities, magnet rows, resume-data persistence, metadata-less.
- Magnets, and multi-file folder torrent creation, plus unit tests for the.
- New helpers.
- ≡ƒñû Generated with Codebuff.
- Co-Authored-By: Codebuff <noreply@codebuff.com>.

## v1.11.3 - 2026-08-16

- Show added torrents in the GUI with libtorrent 2.1 (issue #1).
- Libtorrent 2.1 removed torrent_status.paused/auto_managed (now the.
- Torrent_flags bitmask on status.flags) and session.status(); the row.
- Builder in LocalClient.get_torrents_full then raised on every torrent.
- And the swallowed exception returned an empty list, so added torrents.
- Were invisible while still downloading. Read the flags via.
- Version-agnostic helpers and fall back to summed per-torrent payload.
- Rates for session stats. Also resolve the state enum across versions.
- (queued_for_checking merged into checking_resume_data in 2.1) and.
- Print skipped rows instead of silently blanking the list.
- ≡ƒñû Generated with Codebuff.
- Co-Authored-By: Codebuff <noreply@codebuff.com>.

## v1.11.2 - 2026-08-15

- Count a macOS .app symlinked binary once.
- PyInstaller keeps the real binary under Contents/Frameworks and symlinks it.
- Into Contents/Resources, so the bundle audit saw two libtorrent extensions and.
- Rejected the macOS app. Symlinks are now skipped, which also stops them being.
- Counted twice in the reported bundle size.
- Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>.
- Claude-Session: https://claude.ai/code/session_016Hyts3mKzpCKvWf9JyrBC4.

## v1.11.1 - 2026-08-15

- Report the libtorrent version with the supported attribute.
- Libtorrent 2.1 removed lt.version, so LocalClient.test_connection raised.
- AttributeError and the app reported "Connection failed: module libtorrent has.
- No attribute version" on startup. Use lt.__version__ instead.
- The packaged self-test only read lt.__version__, so it could not see this.
- A test now checks every libtorrent attribute the code reaches for against the.
- Libtorrent the build ships, except the ones guarded by hasattr/getattr.
- The updater tests that simulate Windows now supply the Windows-only subprocess.
- Names, which POSIX does not define, so the macOS job stops failing on them.
- Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>.
- Claude-Session: https://claude.ai/code/session_016Hyts3mKzpCKvWf9JyrBC4.

## v1.11.0 - 2026-08-15

- Ship self-contained packages with verified libtorrent.
- Keep the remote Linux build script intact over ssh.
- Git archive applies the working-tree eol conversion, so tools/build_linux.sh.
- Reached the Linux host with CRLF and bash rejected "set -Eeuo pipefail" as an.
- Invalid option name. Shell scripts are now pinned to LF.
- The remote command was also built as a multi-line string, which lost its.
- Quoting in transit: the host ran a bare "set" that dumped its environment into.
- The build log and left the command running without error handling. It is now a.
- Single line, and it no longer uses a login shell.
- Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>.
- Claude-Session: https://claude.ai/code/session_016Hyts3mKzpCKvWf9JyrBC4.
- Windows now builds locally from the maintained CPython 3.14 libtorrent.
- Wheel, Linux builds over SSH on root@serrebiradio.com, and GitHub Actions.
- Handles macOS only. Broad collect_submodules sweeps are gone and build.
- Dependencies moved to requirements-build.txt, cutting the Windows bundle.
- To about 64 MiB.
- Every build now audits the bundle and runs the frozen executable in a.
- Stripped environment, failing if libtorrent is missing, duplicated,.
- Loaded from outside the bundle, or the wrong version.

## v1.10.0 - 2026-08-09

- Verify self-contained Windows releases.

## v1.9.0 - 2026-08-08

- The torrent search adopts blindDL's indexers when both are installed on the same computer. SerrebiTorrent still ships with none of its own, so anyone who had already set a Prowlarr or Jackett up in blindDL no longer has to type the URL and key in again. It reads a file on your own machine -- nothing about anybody's indexers travels in the release -- and it only ever adds, so an indexer you have edited here is never overwritten.

## v1.8.0 - 2026-08-08

- Search torrent indexers from the Tools menu. Tools, Search for Torrents (Ctrl+F) searches Knaben, The Pirate Bay, EZTV, Nyaa, Torrents-CSV, LimeTorrents and BitSearch at once and adds what you pick to the connected client. Indexers run in parallel and the list fills as each answers, so one slow site does not hold up the rest. Sort by seeders, best match, size, newest or name; Ctrl+C copies magnet links.
- Add your own Torznab or Newznab endpoints under My indexers -- a whole Prowlarr or Jackett instance counts as one. That is how private trackers are searched: those tools already hold the login and the passkey, so SerrebiTorrent never stores a tracker password. A private tracker's authenticated .torrent is fetched with your own credentials when you add it.
- The qBittorrent version reported to trackers and peers is now looked up from qBittorrent's own releases once a day and cached, instead of being a constant that had to be edited before each release.

## v1.7.13 - 2026-07-10

- Tolerate delayed qBittorrent removal.

## v1.7.12 - 2026-07-05

- Speed up app close during update by skipping disk-cache flush.
- Save_state() runs on the blocking shutdown path (busy cursor shown while.
- It waits) and was requesting flush_disk_cache for every torrent's resume.
- Data, forcing a synchronous disk write flush per torrent before the app.
- Could exit. That's what made "closing to install update" feel slow with.
- Several active torrents. The periodic background autosave already added.
- For ratio persistence still flushes for real crash safety, but it runs.
- Off the UI thread and doesn't block anything, so drop the flush from the.
- Blocking shutdown save and tighten its poll timeout accordingly.
- Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>.

## v1.7.11 - 2026-07-05

- Persist seeding ratio/resume data periodically, not only at shutdown.
- Reorganizes sections, adds Telegram community callout, fixes stale.
- Resume data (ratio, upload/download totals) was only flushed to disk when.
- The app fully shut down gracefully. The local libtorrent session already.
- Runs continuously in the background regardless of which client profile.
- (local/remote) is active in the UI, but any crash, force-kill, or.
- Update-triggered restart rolled every torrent's stats back to whatever.
- Was last saved. Add a periodic background autosave so seeding stats.
- Survive regardless of how the process ends or which profile is switched to.
- Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>.
- Version number, and removes duplicate/broken content.

## v1.7.10 - 2026-06-27

- Fix manual updater launcher test.

## v1.7.9 - 2026-06-27

- Fix ci dependency setup.
- Fix release and runtime edge cases.

## v1.7.8 - 2026-06-27

- Fix updater visibility and qbit removal.

## v1.7.7 - 2026-06-21

- Emit list row focus events.

## v1.7.6 - 2026-06-21

- Keep file list arrows speaking.

## v1.7.5 - 2026-06-21

- Keep details synced to focused torrent.

## v1.7.4 - 2026-06-21

- Announce virtual list rows to NVDA on arrow navigation.
- The torrent list, file list, peers, trackers, and RSS article lists are all.
- Wx.LC_VIRTUAL controls. NVDA announces the row carrying wx.LIST_STATE_FOCUSED,.
- But these lists never re-asserted a focused row after a refresh, so arrowing.
- Went silent while Tabbing in still worked:.
- The torrent list's per-row Select() loop ran on every 2-second refresh, and.
- Select() sets only LVIS_SELECTED (never LVIS_FOCUSED), churning the focused.
- Row out from under the user.
- The Files/Peers/Trackers/Article lists called SetItemCount() on every refresh.
- (which wipes the focused row on a virtual list) and never established one.
- Add AccessibleVirtualListMixin: after each populate it re-asserts a single.
- LIST_STATE_FOCUSED row via SetItemState (the state that fires the native MSAA.
- Focus event NVDA reads), but only moves focus when the list actually holds.
- Keyboard focus, so background refreshes never yank focus from elsewhere. The.
- Torrent list preserves the focused row by hash across sort/refresh and.
- Re-applies selection only when the row set actually changed; SetItemCount is.
- Skipped when the count is unchanged.
- Non-virtual controls (ListBox, CheckListBox, LC_SINGLE_SEL ListCtrl, TreeCtrl).
- Keep real per-item accessibles and were already fine.
- Adds display-free unit tests for the focus-restoration decision logic.
- Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>.

## v1.7.3 - 2026-06-21

- Harden remote clients, updater, and web safety; pre-release bug fixes.
- Fix deferred temp-dir cleanup: a PowerShell param() block under.
- Fix the rollback failure dialog to read the log path from.
- Realistic rTorrent fixture; broad coverage across the changed modules.
- Remote clients (clients.py):.
- Report real seeder/leecher counts from peers_complete /.
- Peers_accounted. The connection_seed / connection_leech columns are.
- String constants ("seed"/"leech"), not counts, so the prior mapping.
- Coerced connected peers to 0 for every torrent.
- QBittorrent v5 state normalization and Transmission field handling;.
- SSRF-safe torrent URL download with per-redirect re-validation.
- Updater / release pipeline (updater.py, update_helper.bat):.
- -Command never binds trailing arguments, so the generated cleanup.
- Script silently deleted nothing. Bind paths via environment variables.
- $env:LOG_FILE (same param()-binding defect left it blank).
- Remove the downloaded ZIP + extracted tree on any failed or canceled.
- Update instead of leaking it until the next startup sweep.
- Zip-slip / decompression-bomb caps and Authenticode + manifest.
- Thumbprint verification on update download.
- Web server (web_server.py): SSRF private-IP/DNS-rebind/redirect checks,.
- CSRF protection, and session invalidation on credential change.
- Config default-profile repair; list_torrents no longer flags.
- Benign Windows "operation completed successfully" status as Failed;.
- Drop a redundant duplicate import in clients.py.
- Regression guards for the PowerShell param()-binding defect and a.
- Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>.

## v1.7.2 - 2026-06-20

- Accept release manifest signing thumbprints.

## v1.7.1 - 2026-06-20

- Harden torrent client stability and release safety.

## v1.7.0 - 2026-05-22

- Add announce IP override reported to trackers.
- Add an optional 'Announce IP' preference for the local libtorrent session,.
- Applied via settings_pack announce_ip. Lets the client report a public.
- Relay/VPS address to trackers when inbound peer traffic is port-forwarded.
- From an address that differs from the local egress IP. Blank keeps.
- Automatic detection. Exposed in Local Session Settings -> Connection and.
- Persisted in preferences.
- Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>.

## v1.6.0 - 2026-05-22

- Support BitTorrent v2 / hybrid torrent hashes.
- Track both v1 (btih) and v2 (btmh) info-hashes throughout the local.
- Session, magnet generation, and state restoration so hybrid torrents.
- Are matched, deduped, and restored correctly.
- Session_manager: store per-torrent hash dicts, look up DB/state and.
- Removal by any v1/v2 alias, add hash-dict helpers.
- Torrent_parsing: parse btmh magnets, build hybrid magnet URIs.
- Clients/main: emit v1/v2 hashes and full magnet links (prefer.
- Libtorrent make_magnet_uri) when copying magnets.
- Torrent_creator: build magnet via make_magnet_uri for hybrid output.
- Bump reported qBittorrent version to 5.2.0.
- Tests for btmh parsing and hybrid magnet building.
- Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>.

## v1.5.48 - 2026-05-22

- Fix local hybrid torrent removal.
- Fix release draft cleanup.

## v1.5.47 - 2026-05-22

- Fix local hybrid torrent removal.
