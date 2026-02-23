<#import "template.ftl" as layout>
<#import "field.ftl" as field>
<#import "buttons.ftl" as buttons>
<#import "social-providers.ftl" as identityProviders>
<#import "passkeys.ftl" as passkeys>
<@layout.registrationLayout displayMessage=!messagesPerField.existsError('username','password') displayInfo=realm.password && realm.registrationAllowed && !registrationDisabled??; section>
 <#if section = "header">
<div class="nebula-commander-header">
  <img src="${url.resourcesPath}/img/logo.svg" alt="Nebula Commander" class="nebula-commander-logo"/>
  <h1 class="nebula-commander-title">Nebula Commander</h1>
  <p class="nebula-commander-subtitle">Sign in to manage your Nebula network</p>
</div>
 <#elseif section = "form">
 <form id="kc-form-login" action="${url.loginAction}" method="post">
 <#if realm.password>
 <#if !usernameHidden??>
 <#assign label>Email Address</#assign>
 <@field.input name="username" label=label error=messagesPerField.getFirstError('username','password') autofocus=true autocomplete="username" value=login.username!'' />
 <#else>
 <input type="hidden" id="username" name="username" value="${login.username!''}"/>
 </#if>
 <@field.password name="password" label=msg("password") forgotPassword=realm.resetPasswordAllowed autofocus=usernameHidden?? autocomplete="current-password" />
 <#if realm.rememberMe && !usernameHidden??>
 <@field.checkbox name="rememberMe" label=msg("rememberMe") value=login.rememberMe?? />
 </#if>
 <input type="hidden" id="credentialId" name="credentialId" value="${(auth.selectedCredential)!''}" />
 <@buttons.loginButton />
 <@passkeys.conditionalUIData />
 </#if>
 </form>
 <#elseif section = "socialProviders">
 <#if realm.password && social.providers?? && social.providers?has_content>
 <@identityProviders.show social=social/>
 </#if>
 <#elseif section = "info">
 <#if realm.password && realm.registrationAllowed && !registrationDisabled??>
 ${msg("noAccount")} <a href="${url.registrationUrl}">${msg("doRegister")}</a>
 </#if>
 </#if>
</@layout.registrationLayout>
